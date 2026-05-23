SSO_REGION=us-east-2
PROFILE_ADMIN=admin_tfontana
SSO_INSTANCE_ARN=$(aws sso-admin list-instances --region $SSO_REGION --profile $PROFILE_ADMIN --query 'Instances[0].InstanceArn' --output text)
PS_ARN=arn:aws:sso:::permissionSet/ssoins-6684b776b34e737d/ps-d40740904281e333

aws sso-admin put-inline-policy-to-permission-set \
  --region "$SSO_REGION" --profile "$PROFILE_ADMIN" \
  --instance-arn "$SSO_INSTANCE_ARN" \
  --permission-set-arn "$PS_ARN" \
  --inline-policy file:///Users/teotonio/Projetos/IaaC/iaactools/conf/deny-non-us1-allow-us2-snapshot.json
