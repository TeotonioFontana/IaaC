IaaC - Project root
    .env - Python virtual environment
    doc - Project documentation
    results
        idc
            <home_region>
                identity-store
                assignments
                    list_accounts.json (accounts visible to SSO)
                    list_permission_sets.json
                    list_account_assignments/
                        <accountId>/
                            <permissionSetName>__<shortid>.json (all principals/assignments for that PS in that account)
                    manifest.json (summary of what was exported)
                checks
                    check_idc_recovery.json — machine-readable completeness report
                    check_idc_recovery.txt — human summary of gaps/findings
        cloud-formation
            production
                <region>
                    exported_stack.yaml — raw exported template from cfn_exporter
                    split   
                        <many files> — the split, region-ready templates from cfn_splitter
        backups
            ebs-volumes
                <MANY VOLUMES>
            snapshots
                <many snapshots>
    iaactools - python and shell scripts
        backup 
            idc - identification scripts
            ami - ami scripts   
            cfn - cloud formation scripts
            ebs - block volumes
        recovery
