#!/usr/bin/env python

# may not need this package, but sounds cool...
# from __future__ import print_function
import boto3
import botocore
import time
import sys
import argparse
# added
from getpass import getpass

'''AWS Organizations Create Account and Provision Resources via CloudFormation

This module creates a new account using Organizations, then calls CF

to deploy baseline resources within that account via a local template file.

'''

__version__ = '0.1'
__author__ = '@author@'
__email__ = '@email@'


def create_account(
        account_name,
        account_email,
        access_to_billing,
        scp):

    '''
        Create a new AWS account and add it to an organization
    '''

    client = boto3.client('organizations')

    # see if org exists to add to:
    is_org = client.describe_organization()
    if type(is_org.get('Organization').get('Id')) == str:
        print("Already an organization:  "+str(is_org.get('Organization').get('Id')))
    else:
        try:
            create_org_response = client.create_organization()
        except Exception as ex:
            template = "An exception of type {0} occurred. Arguments:\n{1!r} "
            message = template.format(type(ex).__name__, ex.args)
            print(message)
            sys.exit(1)
        # Wait for the org to be created and then grab the Id
        org_status = 'PENDING_ENABLE'
        while org_status == 'PENDING_ENABLE':
            create_org_status = client.describe_organization()
            create_org_status_response = create_org_status.get('Organization').get('AvailablePolicyTypes').get('Status')
            print("Create organization status "+str(create_org_status_response))
            org_status = create_org_status_response
        if org_status == 'ENABLED':
            organization_id = create_org_response.get('Organization').get('Id')
        elif org_status == 'PENDING_DISABLE':
            print("Organization creation failed: " + create_org_status_response)
            sys.exit(1)
    # now gather root id info
    root_info = client.list_roots(MaxResults=10)
    # TODO find a way to make sure you want the account under this root or another one
    root_id = root_info.get('Roots')[0].get('Id')
    print("Here is the root we are using for OU: "+str(root_id))
    # Checking to see if OU is already created under this root
    print("Now Checking if the OU is already there or not")
    doNotCreate = False
    listed_org_units = client.list_organizational_units_for_parent(ParentId=root_id)
    for ou_s in listed_org_units.get('OrganizationalUnits'):
        if ou_s['Name'] == account_name:
            organization_unit_id = ou_s['Id']
            doNotCreate = True
    # Create OU under root
    if doNotCreate:
        print("OU is already there and using this one: "+str(organization_unit_id))
    else:
        try:
            organization_unit = client.create_organizational_unit(
                ParentId=root_id,
                Name=account_name
            )
            organization_unit_id = organization_unit.get('OrganizationalUnit')['Id']
            print("Created the OU: "+str(organization_unit_id))
        except Exception as ex:
            template = "An exception of type {0} occurred. Arguments:\n{1!r} "
            message = template.format(type(ex).__name__, ex.args)
            # create_organizational_unit(organization_unit_id)
            print(message)
            sys.exit(1)

    # Check to see if account is already created
    print("Now checking if account already exists:")
    listed_accounts = client.list_accounts()
    createNew = True
    for accounter in listed_accounts.get('Accounts'):
        print("Now Checking: "+str(accounter.get('Name')))
        # TODO make this a more accurate match, TestPython matches TestPython1 for instance
        if accounter.get('Name') in account_name:
            print("Found account!  "+str(account_name))
            account_id = accounter.get('Id')
            createNew = False
    # Creating account if we need to
    if createNew:
        print("Creating new account: " + account_name + " (" + account_email + ")")
        try:
            create_account_response = client.create_account(Email=account_email, AccountName=account_name,
                                                            IamUserAccessToBilling=access_to_billing)
        except botocore.exceptions.ClientError as e:
            print(e)
            sys.exit(1)

        time.sleep(10)

        account_status = 'IN_PROGRESS'
        while account_status == 'IN_PROGRESS':
            create_account_status_response = client.describe_create_account_status(
                CreateAccountRequestId=create_account_response.get('CreateAccountStatus').get('Id'))
            print("Create account status "+str(create_account_status_response))
            account_status = create_account_status_response.get('CreateAccountStatus').get('State')
        if account_status == 'SUCCEEDED':
            account_id = create_account_status_response.get('CreateAccountStatus').get('AccountId')
            print("Account Created! Now moving it to the OU.")
        elif account_status == 'FAILED':
            print("Account creation failed: " + create_account_status_response.get('CreateAccountStatus').get('FailureReason'))
            sys.exit(1)
    else:
        print("Account already created, now moving it to the OU.")

    # now we need to check and see if the account was moved already
    accountMove = True
    get_accounts = client.list_accounts_for_parent(ParentId=organization_unit_id)
    for counts in get_accounts.get('Accounts'):
        if counts.get('Id') in account_id:
            accountMove = False
            print("Account already moved")
    if accountMove:
        print("Moving account into OU")
        try:
            move_account_response = client.move_account(AccountId=account_id, SourceParentId=root_id,
                                                        DestinationParentId=organization_unit_id)
        except Exception as ex:
            template = "An exception of type {0} occurred. Arguments:\n{1!r} "
            message = template.format(type(ex).__name__, ex.args)
            print(message)

    # Attach policy to account if exists
    if scp is not None:
        attach_policy_response = client.attach_policy(PolicyId=scp, TargetId=account_id)
        print("Attach policy response "+str(attach_policy_response))

    return account_id


def assume_role(account_id, account_role):
    '''
        Assume admin role within the newly created account and return credentials
    '''
    sts_client = boto3.client('sts')
    role_arn = 'arn:aws:iam::' + account_id + ':role/' + account_role

    # Call the assume_role method of the STSConnection object and pass the role
    # ARN and a role session name.

    assuming_role = True
    while assuming_role is True:
        try:
            assuming_role = False
            assumedRoleObject = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="NewAccountRole"
            )
        except botocore.exceptions.ClientError as e:
            assuming_role = True
            print(e)
            print("Retrying...")
            time.sleep(10)

    # From the response that contains the assumed role, get the temporary
    # credentials that can be used to make subsequent API calls
    return assumedRoleObject['Credentials']


def get_template(template_file):

    '''
        Read a template file and return the contents
    '''

    print("Reading resources from " + template_file)
    f = open(template_file, "r")
    cf_template = f.read()
    return cf_template


def deploy_resources(credentials, template, stack_name, stack_region, admin_username, admin_password):

    '''
        Create a CloudFormation stack of resources within the new account
    '''

    datestamp = time.strftime("%d/%m/%Y")
    client = boto3.client('cloudformation',
                          aws_access_key_id=credentials['AccessKeyId'],
                          aws_secret_access_key=credentials['SecretAccessKey'],
                          aws_session_token=credentials['SessionToken'],
                          region_name=stack_region)
    print("Creating stack " + stack_name + " in " + stack_region)

    creating_stack = True
    while creating_stack is True:
        try:
            creating_stack = False
            create_stack_response = client.create_stack(
                StackName=stack_name,
                TemplateBody=template,
                Parameters=[
                    {
                        'ParameterKey': 'AdminUsername',
                        'ParameterValue': admin_username
                    },
                    {
                        'ParameterKey': 'AdminPassword',
                        'ParameterValue': admin_password
                    }
                ],
                NotificationARNs=[],
                Capabilities=[
                    'CAPABILITY_NAMED_IAM',
                ],
                OnFailure='ROLLBACK',
                Tags=[
                    {
                        'Key': 'ManagedResource',
                        'Value': 'True'
                    },
                    {
                        'Key': 'DeployDate',
                        'Value': datestamp
                    }
                ]
            )
        except botocore.exceptions.ClientError as e:
            creating_stack = True
            print(e)
            print("Retrying...")
            time.sleep(10)

    stack_building = True
    print("Stack creation in process...")
    print(create_stack_response)
    while stack_building is True:
        event_list = client.describe_stack_events(StackName=stack_name).get("StackEvents")
        stack_event = event_list[0]

        if (stack_event.get('ResourceType') == 'AWS::CloudFormation::Stack' and
           stack_event.get('ResourceStatus') == 'CREATE_COMPLETE'):
            stack_building = False
            print("Stack construction complete.")
        elif (stack_event.get('ResourceType') == 'AWS::CloudFormation::Stack' and
              stack_event.get('ResourceStatus') == 'ROLLBACK_COMPLETE'):
            stack_building = False
            print("Stack construction failed.")
            sys.exit(1)
        else:
            print(stack_event)
            print("Stack building . . .")
            time.sleep(10)

    stack = client.describe_stacks(StackName=stack_name)
    return stack

# TODO find a way to check for valid creds and print region/username/etc
# def checkCreds():


def main(arguments):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--account_name', required=True)
    parser.add_argument('--account_email', required=True)
    parser.add_argument('--account_role',
                        default=None)
    parser.add_argument('--template_file',
                        default='baseline.yml')
    parser.add_argument('--stack_name',
                        default='Baseline')
    parser.add_argument('--stack_region',
                        default='us-west-1')
    parser.add_argument('--admin_username')
    # parser.add_argument(action='store_true', dest='admin_password', help='hidden password prompt')
    args = parser.parse_args(arguments)

    # if args.admin_password:
    #     admin_password = getpass(prompt='Please enter the admin password: ')

    # always allow this for my Orgs
    access_to_billing = "ALLOW"
    scp = None
    # Check and see if there is a role to assume for account
    print("Starting the account creation process: ")
    account_id = create_account(args.account_name, args.account_email, access_to_billing, scp)
    # Comment the above line and uncomment the below line to skip account creation and just test Cfn deployment (for testing)
    # account_id = "481608673808"
    print("Account: " + account_id)
    if args.account_role is None:
        print("only creating account and not adding the stack")
    else:
        credentials = assume_role(account_id, args.account_role)
        print("Deploying resources from " + args.template_file + " as " + args.stack_name + " in " + args.stack_region)
        template = get_template(args.template_file)
        stack = deploy_resources(credentials, template, args.stack_name, args.stack_region, args.admin_username, args.admin_password)
        print(stack)
    print("Resources deployed for account " + account_id + " (" + args.account_email + ")")


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
