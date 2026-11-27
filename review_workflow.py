"""Atomic human-approved upload state transitions."""


def claim_upload(conn, job_id):
    """Only one API/Streamlit request can claim a review-pending job."""
    cursor = conn.execute(
        "UPDATE pipeline_jobs SET stage='업로드 진행 중' WHERE id=? AND stage='최종컨펌 대기'",
        (job_id,),
    )
    return cursor.rowcount == 1


def upload_result_stage(ok, privacy_unverified=False):
    if ok:
        return "업로드 완료(비공개)"
    if privacy_unverified:
        return "업로드 상태 확인 필요"
    return "최종컨펌 대기"
