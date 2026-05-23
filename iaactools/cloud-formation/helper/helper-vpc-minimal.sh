aws cloudformation deploy \
  --profile "architect" \
  --region us-east-1 \
  --stack-name helper-vpc-minimal \
  --template-file helper-vpc-minimal.yaml \
  --parameter-overrides \
    EnvironmentName=helper \
    VpcCidr=10.100.0.0/24 \
    PublicSubnetCidr=10.100.0.0/25 \
--no-fail-on-empty-changeset
