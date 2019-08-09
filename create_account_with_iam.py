#Copyright 2008-2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.

#Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance with the License. A copy of the License is located at
#http://aws.amazon.com/apache2.0/
#or in the "license" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.


#!/usr/bin/env python

from __future__ import print_function
import boto3
import botocore
import time
import sys
import argparse

'''AWS Organizations Create Account and Provision Resources via CloudFormation

This module creates a new account using Organizations, then calls CloudFormation to deploy baseline resources within that account via a local tempalte file.

'''

__version__ = '0.1'
__author__ = '@author@'
__email__ = '@email@'


def create_account(
        account_name,
        account_email,
        account_role,
        access_to_billing,
        organization_unit_id,
        scp):

    '''
        Create a new AWS account and add it to an organization
    '''

    client = boto3.client('organizations')
    try:
        create_account_response = client.create_account(Email=account_email, AccountName=account_name,
                                                        RoleName=account_role,
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
    elif account_status == 'FAILED':
        print("Account creation failed: " + create_account_status_response.get('CreateAccountStatus').get('FailureReason'))
        sys.exit(1)
    root_id = client.list_roots().get('Roots')[0].get('Id')

    # Move account to the org
    if organization_unit_id is not None:
        try:
            describe_organization_response = client.describe_organizational_unit(
                OrganizationalUnitId=organization_unit_id)
            move_account_response = client.move_account(AccountId=account_id, SourceParentId=root_id,
                                                        DestinationParentId=organization_unit_id)
        except Exception as ex:
            template = "An exception of type {0} occurred. Arguments:\n{1!r} "
            message = template.format(type(ex).__name__, ex.args)
            # create_organizational_unit(organization_unit_id)
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
                        'ParameterKey' : 'AdminUsername',
                        'ParameterValue' : admin_username
                    },
                    {
                        'ParameterKey' : 'AdminPassword',
                        'ParameterValue' : admin_password
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


def main(arguments):

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--account_name', required=True)
    parser.add_argument('--account_email', required=True)
    parser.add_argument('--account_role',
                        default='OrganizationAccountAccessRole')
    parser.add_argument('--template_file',
                        default='baseline.yml')
    parser.add_argument('--stack_name',
                        default='Baseline')
    parser.add_argument('--stack_region',
                        default='us-east-1')
    parser.add_argument('--admin_username', required=True)
    parser.add_argument('--admin_password', required=True)
    args = parser.parse_args(arguments)

    access_to_billing = "DENY"
    organization_unit_id = None
    scp = None

    print("Creating new account: " + args.account_name + " (" + args.account_email + ")")
    account_id = create_account(args.account_name, args.account_email, args.account_role, access_to_billing, organization_unit_id, scp)
    # Comment the above line and uncomment the below line to skip account creation and just test Cfn deployment (for testing)
    # account_id = "481608673808"
    print("Created acount: " + account_id)
    credentials = assume_role(account_id, args.account_role)

    print("Deploying resources from " + args.template_file + " as " + args.stack_name + " in " + args.stack_region)
    template = get_template(args.template_file)
    stack = deploy_resources(credentials, template, args.stack_name, args.stack_region, args.admin_username, args.admin_password)
    print(stack)
    print("Resources deployed for account " + account_id + " (" + args.account_email + ")")


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
