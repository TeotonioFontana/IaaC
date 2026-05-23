#Split only (current behavior):

cfn_splitter --input tf-stack.yaml --out-dir out/


#Split + DR transform for us-east-1:

cfn_splitter --input tf-stack.yaml --out-dir out-dr/ --dest-region us-east-1 --preview


#Dry-run (don’t write files, just show a summary):

cfn_splitter --input tf-stack.yaml --dest-region us-east-1 --dry-run

python3 cfn_splitter.py --input cloud-formation/production/us-east-2/tf-stack.yaml --dest-region us-east-1 --output /Users/teotonio/Projetos/IaaC/iaactools/cloud-formation/production/us-east-1