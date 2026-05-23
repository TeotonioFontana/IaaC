aws cloudformation deploy \
  --profile architect \
  --region us-east-1 \
  --stack-name helper-minimal \
  --template-file helper-instance-minimal.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    EnvironmentName=helper \
    VpcCidr=10.100.0.0/24 \
    PublicSubnetCidr=10.100.0.0/25 \
    InstanceType=t3.micro \
    AmiId='' \
    BackupBucketName=212533511020-tf-iaac-ebs-volumes \
    BackupBucketPrefix=tf-backup/ \
    KmsKeyArn='arn:aws:kms:us-east-1:212533511020:key/5ef4a1ff-0e31-4bc5-888e-85801a14e753' \
    EgressPolicy=web
