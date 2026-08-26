"""
Real-Time Vision, CCTV & Motion Alert Suite
"""

import base64
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

st.set_page_config(
    page_title="Real-Time Vision, CCTV & Motion Alert Suite",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .main-title { font-size: 2.3rem; font-weight: 800; color: #0F172A; letter-spacing: -0.025em; }
        .sub-title { font-size: 1.05rem; color: #475569; font-weight: 400; }
        .secure-banner { background: #064E3B; color: #ECFDF5; padding: 12px 18px; border-radius: 8px; font-weight: 500; font-size: 0.95rem; }
        .honesty-banner { background: #7C2D12; color: #FEF3C7; padding: 10px 16px; border-radius: 8px; font-weight: 500; font-size: 0.9rem; }
        .alert-red { background: #7F1D1D; color: #FEF2F2; padding: 10px 15px; border-radius: 6px; font-weight: 600; }
        .alert-green { background: #064E3B; color: #ECFDF5; padding: 10px 15px; border-radius: 6px; font-weight: 600; }
        .stButton>button { border-radius: 8px; font-weight: 600; padding: 0.5rem 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

OUTPUT_DIR = Path("cctv_audit_output")
OUTPUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("cctv_suite")

for key, default in [
    ("short_term_cache", None),
    ("long_term_vault", {}),
    ("alert_logs", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================================
# REAL ENCRYPTION HELPERS (PBKDF2 -> Fernet), replacing the fake hash-gate
# ============================================================================

def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_bytes(data: bytes, password: str) -> dict:
    salt = np.random.bytes(16)
    key = _derive_key(password, salt)
    token = Fernet(key).encrypt(data)
    return {"salt": salt, "ciphertext": token}


def decrypt_bytes(vault_entry: dict, password: str) -> bytes | None:
    key = _derive_key(password, vault_entry["salt"])
    try:
        return Fernet(key).decrypt(vault_entry["ciphertext"])
    except InvalidToken:
        return None


# ============================================================================
# REAL MOTION-BASED VISION ENGINE (replaces the random-number generator)
# ============================================================================

class MotionAnalysisEngine:
    """
    Captures a short burst of real frames from a webcam / RTSP source /
    uploaded video and estimates activity level using MOG2 background
    subtraction on actual pixel data. This is a real signal (it reacts to
    real motion/occlusion in frame) but it is NOT a trained object
    detector or person-counter — it should be presented to clients as a
    motion/activity estimate, not a precise headcount.
    """

    def __init__(self, source):
        self.source = source

    def analyze(self, crowd_threshold: int, n_frames: int = 25) -> dict:
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            return {
                "opened": False,
                "error": "Could not open the video source. Check the camera index, "
                         "RTSP URL/credentials, or uploaded file.",
            }

        bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=25, detectShadows=True)
        motion_ratios = []
        last_frame = None
        for _ in range(n_frames):
            ret, frame = cap.read()
            if not ret:
                break
            last_frame = frame
            fg_mask = bg_subtractor.apply(frame)
            # Ignore shadow pixels (value 127 in MOG2's shadow-detection mode)
            motion_pixels = np.count_nonzero(fg_mask == 255)
            total_pixels = fg_mask.size
            motion_ratios.append(motion_pixels / total_pixels)
        cap.release()

        if not motion_ratios:
            return {"opened": True, "error": "Source opened but returned no frames."}

        # Use the stable back half of the burst — MOG2 needs a few frames to
        # build its background model, so the first several are noisy.
        stable = motion_ratios[len(motion_ratios) // 2:] or motion_ratios
        avg_motion_ratio = float(np.mean(stable))

        # Heuristic, clearly-labeled conversion from motion ratio to an
        # activity estimate — this is not a calibrated headcount.
        estimated_activity = int(round(avg_motion_ratio * 400))
        is_breach = estimated_activity > crowd_threshold

        return {
            "opened": True,
            "error": None,
            "source": str(self.source),
            "frames_analyzed": len(motion_ratios),
            "avg_motion_ratio": round(avg_motion_ratio, 4),
            "estimated_activity": estimated_activity,
            "threshold_limit": crowd_threshold,
            "is_breach": is_breach,
            "last_frame_rgb": cv2.cvtColor(last_frame, cv2.COLOR_BGR2RGB) if last_frame is not None else None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


# --------------------------------------------------------------------------
# SIDEBAR — VAULT MANAGER (now with real encryption)
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🧠 Memory & Vault Manager")
    st.markdown("Short-term session cache plus a **genuinely encrypted** long-term vault "
                "(AES via Fernet, key derived from your password with PBKDF2).")
    st.divider()

    st.markdown("#### 📦 Long-Term Secure Vault")
    if st.session_state.long_term_vault:
        st.success(f"{len(st.session_state.long_term_vault)} audit report(s) vaulted.")
        selected_vault_item = st.selectbox("Select Vault Item", list(st.session_state.long_term_vault.keys()))
        vault_pwd_input = st.text_input("Vault Decryption Password", type="password", key="vault_unlock_pwd")

        col_v1, col_v2 = st.columns(2)
        with col_v1:
            if st.button("Unlock & Download"):
                record = st.session_state.long_term_vault[selected_vault_item]
                plaintext = decrypt_bytes(record, vault_pwd_input) if vault_pwd_input else None
                if plaintext is not None:
                    st.success("Access Granted — decrypted successfully.")
                    st.download_button(
                        "📥 Get Decrypted Report",
                        data=plaintext,
                        file_name=f"{selected_vault_item}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    st.error("Incorrect password — decryption failed.")
        with col_v2:
            if st.button("Purge Vault Item"):
                del st.session_state.long_term_vault[selected_vault_item]
                st.rerun()
    else:
        st.info("Vault is currently empty.")

    st.divider()
    if st.button("🧹 Clear All Session & Memory", type="secondary"):
        st.session_state.short_term_cache = None
        st.session_state.long_term_vault = {}
        st.session_state.alert_logs = []
        st.rerun()


# --------------------------------------------------------------------------
# MAIN INTERFACE
# --------------------------------------------------------------------------
st.markdown('<p class="main-title">🚨 Real-Time Vision, CCTV & Motion Alert Suite</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-title">Real webcam/RTSP/video analysis using OpenCV background subtraction, threshold alerts, and an encrypted vault.</p>', unsafe_allow_html=True)
st.markdown("---")

st.markdown(
    """
    <div class="honesty-banner">
        ℹ️ <b>What this actually measures:</b> the "activity" number below comes from real
        pixel-level motion analysis on live frames (OpenCV MOG2 background subtraction) — it
        is a genuine motion signal, but it is a heuristic activity estimate, not a calibrated
        person-count from a trained detector. Treat breach alerts as "something moved a lot
        here," not "N people confirmed present."
    </div>
    """,
    unsafe_allow_html=True,
)
st.markdown("<br>", unsafe_allow_html=True)

tab_cctv, tab_vault_logs = st.tabs(["📹 Camera / Video Motion Analysis", "📂 Memory & Vault Registry"])

with tab_cctv:
    st.markdown("### 🔴 Camera, RTSP Stream & Video File Analysis")
    st.markdown("Captures a short burst of real frames and analyzes actual motion — no simulated numbers.")

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        input_type = st.radio("Select Input Mode", ["Local Webcam / RTSP Link", "Upload Video File (.mp4 / .avi)"])
        uploaded_video = None
        if input_type == "Local Webcam / RTSP Link":
            stream_source = st.text_input(
                "Camera Source (e.g. '0' for default webcam, or 'rtsp://user:pass@ip:554/stream')", "0"
            )
            source_label = f"Camera_{stream_source}"
        else:
            uploaded_video = st.file_uploader("Upload Video File", type=["mp4", "avi", "mov"])
            source_label = uploaded_video.name if uploaded_video else "Uploaded_Video.mp4"

    with col_c2:
        crowd_limit = st.slider("Activity Alert Threshold", min_value=5, max_value=150, value=40,
                                 help="Estimated activity score above this triggers a breach alert.")
        n_frames = st.slider("Frames to Sample per Analysis", 10, 60, 25,
                              help="More frames = more stable estimate, takes slightly longer.")
        enable_sms_dispatch = st.checkbox("Log breach events to the incident history below", value=True)

    if st.button("▶️ Run Motion Analysis", type="primary"):
        video_source = None
        tmp_path = None
        if input_type == "Local Webcam / RTSP Link":
            video_source = int(stream_source) if stream_source.isdigit() else stream_source
        elif uploaded_video is not None:
            tmp_path = Path("cctv_audit_output") / uploaded_video.name
            tmp_path.write_bytes(uploaded_video.getvalue())
            video_source = str(tmp_path)
        else:
            st.error("Please upload a video file first.")

        if video_source is not None:
            with st.spinner(f"Capturing and analyzing {n_frames} real frames..."):
                engine = MotionAnalysisEngine(video_source)
                result = engine.analyze(crowd_limit, n_frames=n_frames)

            if result.get("error"):
                st.error(result["error"])
            else:
                if result["last_frame_rgb"] is not None:
                    st.image(result["last_frame_rgb"], caption="Last analyzed frame", use_container_width=True)

                if result["is_breach"]:
                    st.markdown(
                        f'<div class="alert-red">⚠️ Activity threshold breached '
                        f'(estimated activity: {result["estimated_activity"]} / limit: {crowd_limit})</div>',
                        unsafe_allow_html=True,
                    )
                    if enable_sms_dispatch:
                        entry = (f"[{result['timestamp']}] BREACH: {source_label} — "
                                 f"estimated activity {result['estimated_activity']} "
                                 f"(motion ratio {result['avg_motion_ratio']})")
                        st.session_state.alert_logs.append(entry)
                else:
                    st.markdown(
                        f'<div class="alert-green">✅ Normal — estimated activity '
                        f'{result["estimated_activity"]} / limit {crowd_limit}</div>',
                        unsafe_allow_html=True,
                    )

                m1, m2, m3 = st.columns(3)
                m1.metric("Estimated activity", result["estimated_activity"])
                m2.metric("Frames analyzed", result["frames_analyzed"])
                m3.metric("Motion pixel ratio", f'{result["avg_motion_ratio"]:.2%}')

                summary_df = pd.DataFrame([
                    {"Parameter": "Source", "Detail": result["source"]},
                    {"Parameter": "Frames Analyzed", "Detail": result["frames_analyzed"]},
                    {"Parameter": "Avg Motion Pixel Ratio", "Detail": result["avg_motion_ratio"]},
                    {"Parameter": "Estimated Activity Score", "Detail": result["estimated_activity"]},
                    {"Parameter": "Threshold Limit", "Detail": result["threshold_limit"]},
                    {"Parameter": "Breach", "Detail": str(result["is_breach"])},
                    {"Parameter": "Timestamp", "Detail": result["timestamp"]},
                ])
                st.session_state.short_term_cache = {
                    "type": "motion_audit",
                    "filename": f"motion_audit_{source_label.split('.')[0].lower()}",
                    "summary_df": summary_df,
                    "timestamp": result["timestamp"],
                }

            if tmp_path and tmp_path.exists():
                tmp_path.unlink()

    if st.session_state.alert_logs:
        st.markdown("---")
        st.markdown("#### 🚨 Incident History (this session)")
        for log in reversed(st.session_state.alert_logs[-5:]):
            st.code(log)

with tab_vault_logs:
    st.markdown("### 📂 Memory Manager & Secure Vault")

    if st.session_state.short_term_cache is not None:
        cache = st.session_state.short_term_cache
        st.info(f"Active Short-Term Cache: **{cache['filename']}** ({cache['timestamp']})")
        st.dataframe(cache["summary_df"], use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🔒 Save to Encrypted Long-Term Vault")
        enable_vault_save = st.checkbox("Encrypt and store audit package in Long-Term Vault")
        vault_name_input = st.text_input("Vault Record Title", value=cache["filename"])
        vault_file_pwd = st.text_input("Set Vault Password", type="password",
                                        placeholder="Required — used to derive the encryption key")

        if st.button("📥 Commit to Vault & Download Package", type="primary"):
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                cache["summary_df"].to_excel(writer, sheet_name="Motion Audit Summary", index=False)
            excel_bytes = buffer.getvalue()

            if enable_vault_save:
                if not vault_name_input:
                    st.error("Give the vault record a title.")
                elif not vault_file_pwd:
                    st.error("A password is required to encrypt this entry — there is no default fallback.")
                else:
                    st.session_state.long_term_vault[vault_name_input] = {
                        **encrypt_bytes(excel_bytes, vault_file_pwd),
                        "timestamp": cache["timestamp"],
                    }
                    st.success(f"'{vault_name_input}' encrypted and stored in the vault.")

            st.download_button(
                label="📥 Download Audit Report (.xlsx, unencrypted copy)",
                data=excel_bytes,
                file_name=f"{cache['filename']}_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.info("No active cache in short-term memory. Run a motion analysis first.")

    st.markdown("---")
    st.markdown("#### 🛡️ Vault Summary Overview")
    if st.session_state.long_term_vault:
        vault_overview = [
            {"Report Name": name, "Timestamp": info["timestamp"], "Security": "AES-encrypted (Fernet/PBKDF2) 🔐"}
            for name, info in st.session_state.long_term_vault.items()
        ]
        st.dataframe(pd.DataFrame(vault_overview), use_container_width=True)
    else:
        st.write("Vault is currently empty.")
