# AccountCreator

This repo is for a lightning talk that will be given to the python meetup group. 


## Overview

Problem to solve:  Needed to create a seperate AWS account for a business unit process to seperate from PCI environment.  Also, the only service needed in this account was S3.  

Current solution:  Create an account under our root organization but off a difference branch than the PCI network.  Allows access from our Billing account to centralize billing and create IAM users and roles to allow the following access:

1. Allow 3rd party organization to replicate their S3 objects to our S3 bucket.
2. Allow developers to get into AWS and generate API creds to test out SDK functionality with new process.
3. Allow service role from non-AWS infrastructure

AWS does a really great job and provides a detailed walkthrough with scripts and all to accomplish this.  [Source](https://aws.amazon.com/blogs/security/how-to-use-aws-organizations-to-automate-end-to-end-account-creation/)  

However most examples want to create networking and spin up an EC2 instance and add a role.    


## Seperation of Duties and Accounts

AWS has a way to create an account hierarchy that inherits policies and all that.  Much like Active Directory with their group policies, AWS has Organizations that have Organizational units that you can put an AWS account under.  

AWS Organization Layout:
![alt text](https://docs.aws.amazon.com/organizations/latest/userguide/images/BasicOrganization.png "AWS Org")

This is meant to simplify and centralize management to make seperation of duties, consolodated billings, create logical security boundaries for compliance between your companies AWS services and [so much more](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_introduction.html).  


### Boto Gotchas

The Good   
1. Doing AWS tasks with boto3 is easy and fun.  
2. boto3 seems to be the first place automation code is built to wrap new AWS APIs.
3. The only way I found to create and manage AWS organizations without wrapping the API yourself. 
 
The Bad  
1.  No easy way to re-run code to validate environment is the same.
    * Unless you build these checks in your scripts
2.  No easy way to roll back changes unless you write that into the code.
    * Calling a cloudformation stack as often as possible helps with this
    * this also ties into number 1 - configuration management is hard


### Running the codes

First you need to make sure you have valid credentials where boto can see them.  You have options here, and I like to use files or a 'securestring' input to a script.  I don't like passing the string in a command on the CLI since the history will show the password.  However the flat file is not much better, since it is in plaintext too.  

For windows I updated the credentials and config file here:  
`$USERPROFILE\.aws\`  

Once you have those updated, you can seemlessly run the script.  

***WARNING***  
I have not tested the deploy resources portion using the yml cloudconfiguration.  Run that part at your own risk.

I updated AWS supplied python script to not only create an account, but check if there is an organzation, if not create it, then make an organization unit with the same name as the account and then create the account.  

Command would look like this to just create an account and ou with the name test and have test@userDomain.com as the root account email:  

`python .\create_account_with_iam.py --account_name test --account_email test@userDomain.com`  

