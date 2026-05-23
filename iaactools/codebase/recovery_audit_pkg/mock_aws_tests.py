# -*- coding: utf-8 -*-
"""
===============================================================================
 mock_aws_tests.py — v4.0.0-alpha1
===============================================================================
 Purpose............: Synthetic AWS mocks for offline validation of all phases.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides minimalistic fake boto3 clients that emulate S3/EC2 behaviors for
 testing without AWS credentials. Used in automated test suites.
===============================================================================
"""
import json, logging

class MockS3Client:
    """Fake S3 client returning controlled results."""
    def __init__(self): self.storage = {}
    def list_objects_v2(self, Bucket, Prefix):
        return {"KeyCount": 1, "Contents": [{"Key": f"{Prefix}dummy.txt"}]}
    def get_object(self, Bucket, Key):
        fake_manifest = {"Backups": [{"VolumeId": "vol-001", "DstSnapshotId": "snap-001"}]}
        return {"Body": FakeBody(json.dumps(fake_manifest))}
class FakeBody:
    def __init__(self, data): self._data = data.encode()
    def read(self): return self._data

class MockEC2Client:
    """Fake EC2 client emulating snapshot states."""
    def describe_snapshots(self, SnapshotIds):
        return {"Snapshots": [{"SnapshotId": SnapshotIds[0], "State": "completed"}]}

def inject_mocks(monkeypatch):
    """Replace boto3.client with mocks for unit testing."""
    import boto3
    def fake_client(service, *a, **kw):
        if service == "s3": return MockS3Client()
        if service == "ec2": return MockEC2Client()
        raise ValueError(f"Unsupported service {service}")
    monkeypatch.setattr(boto3, "client", fake_client)
    logging.getLogger().info("Injected mock AWS clients.")

if __name__ == "__main__":
    print("Synthetic AWS mock test harness loaded.")
