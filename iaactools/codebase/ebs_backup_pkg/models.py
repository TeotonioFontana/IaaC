from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class BackupRecord:
    VolumeId: str
    VolumeType: str
    SizeGiB: int
    AvailabilityZone: str
    SrcRegion: str
    DstRegion: str
    SrcSnapshotId: Optional[str] = None
    DstSnapshotId: Optional[str] = None
    FullVolumeS3Bucket: Optional[str] = None
    FullVolumeS3Key: Optional[str] = None
    StartTime: str = ""
    EndTime: str = ""
    Tags: Optional[Dict[str, str]] = None
    Error: Optional[str] = None
