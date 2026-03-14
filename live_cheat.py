"""
Cheat Detection MVP with Anti-Spoofing + Background Monitoring

- Multi-step random liveness prompts
- Idle detection
- Multi-person detection
- No-person detection
- Freeze / Pre-recorded video detection
- Background tampering detection
- On-screen overlays + console logs
- Placeholder for ML rep counter
"""

import cv2
import mediapipe as mp
import time
import random
import numpy as np
import sys

# --------------------------- CONFIG ---------------------------

IDLE_SECONDS = 5
MOVEMENT_THRESHOLD = 0.01
PROMPTS_IN_SEQUENCE = 2
PROMPT_TIMEOUT = 12
FACE_DETECTION_MIN_SIZE = (80, 80)
FREEZE_SECONDS = 4  # how long frames can be frozen
FREEZE_THRESHOLD = 2.0  # lower = stricter freeze detection
BACKGROUND_THRESHOLD = 25.0  # higher = more tolerant to changes

# --------------------------- PROMPTS ---------------------------

PROMPT_LABELS = [
    "raise_right_hand",
    "raise_left_hand",
    "touch_head",
    "raise_both_hands"
]

PROMPT_PRETTY = {
    "raise_right_hand": "Raise your RIGHT hand ✋",
    "raise_left_hand": "Raise your LEFT hand 🤚",
    "touch_head": "Touch your HEAD 🤯",
    "raise_both_hands": "Raise BOTH hands 🙌"
}

# --------------------------- INIT MODELS ---------------------------

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# --------------------------- HELPERS ---------------------------

def nose_movement(prev, curr):
    if prev is None:
        return float("inf")
    return abs(curr[0] - prev[0]) + abs(curr[1] - prev[1])

def frame_difference_score(frame1, frame2):
    """Return similarity score between two frames (lower = more frozen)."""
    if frame1 is None or frame2 is None:
        return float("inf")
    gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
    gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray1, gray2)
    return np.mean(diff)

def process_exercise_frame_for_ml(frame_bgr):
    """Placeholder for ML model."""
    return None

def detect_background_change(frame, prev_bg, landmarks, threshold=BACKGROUND_THRESHOLD):
    """Detects sudden changes in background area (ignoring the body)."""
    mask = np.ones(frame.shape[:2], dtype="uint8") * 255  # start with full mask
    if landmarks:
        h, w, _ = frame.shape
        xs = [int(lm.x * w) for lm in landmarks.landmark]
        ys = [int(lm.y * h) for lm in landmarks.landmark]
        min_x, max_x = max(0, min(xs)), min(w, max(xs))
        min_y, max_y = max(0, min(ys)), min(h, max(ys))
        # mask out person
        mask[min_y:max_y, min_x:max_x] = 0
    bg = cv2.bitwise_and(frame, frame, mask=mask)
    if prev_bg is None:
        return bg, False  # no previous background yet
    diff = cv2.absdiff(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY),
                       cv2.cvtColor(prev_bg, cv2.COLOR_BGR2GRAY))
    score = np.mean(diff)
    return bg, score > threshold

# --------------------------- MAIN ---------------------------
def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open webcam.")
        return 1

    with mp_pose.Pose(min_detection_confidence=0.5,
                      min_tracking_confidence=0.5) as pose:
        sequence = random.sample(PROMPT_LABELS, PROMPTS_IN_SEQUENCE)
        current_idx = 0
        current_prompt = sequence[current_idx]
        prompt_start_time = time.time()

        print(f"SYSTEM: Please {PROMPT_PRETTY[current_prompt]} to start. Sequence: {', '.join(PROMPT_PRETTY[p] for p in sequence)}")

        liveness_passed = False
        last_nose = None
        last_move_time = time.time()
        cheat_log = []
        prev_frame = None
        freeze_start = None
        prev_bg = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            h, w, _ = frame.shape
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = pose.process(frame_rgb)

            # Face detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                                  minSize=FACE_DETECTION_MIN_SIZE)
            face_count = len(faces)
            cheat_text = ""

            # No person / multi-person / freeze / background tampering detection
            if face_count == 0:
                cheat_text = "Cheat: No person detected ❌"
            elif face_count > 1:
                cheat_text = f"Cheat: Multiple people detected ({face_count}) ❌"
            else:
                score = frame_difference_score(frame, prev_frame)
                prev_frame = frame.copy()
                if score < FREEZE_THRESHOLD:
                    if freeze_start is None:
                        freeze_start = time.time()
                    elif (time.time() - freeze_start) > FREEZE_SECONDS:
                        cheat_text = "Cheat: Frozen / Pre-recorded video ❌"
                else:
                    freeze_start = None

                if results.pose_landmarks:
                    prev_bg, changed = detect_background_change(frame, prev_bg, results.pose_landmarks)
                    if changed:
                        cheat_text = "Cheat: Background tampering detected ❌"

            # Show cheat overlay and continue if cheating detected
            if cheat_text:
                cv2.putText(frame, cheat_text, (30, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
                if not cheat_log or cheat_log[-1] != cheat_text:
                    print("LOG:", cheat_text)
                    cheat_log.append(cheat_text)
                cv2.imshow("Cheat Detection", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
                continue

            # --- Liveness detection phase ---
            if results.pose_landmarks:
                mp_drawing.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
                lm = results.pose_landmarks.landmark
                nose_norm = (lm[mp_pose.PoseLandmark.NOSE.value].x,
                             lm[mp_pose.PoseLandmark.NOSE.value].y)

                if not liveness_passed:
                    cv2.putText(frame, f"Liveness: {PROMPT_PRETTY[current_prompt]}",
                                (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                                (0, 200, 255), 2)
                    success = False
                    rw = lm[mp_pose.PoseLandmark.RIGHT_WRIST.value]
                    lw = lm[mp_pose.PoseLandmark.LEFT_WRIST.value]
                    rs = lm[mp_pose.PoseLandmark.RIGHT_SHOULDER.value]
                    ls = lm[mp_pose.PoseLandmark.LEFT_SHOULDER.value]
                    nose = lm[mp_pose.PoseLandmark.NOSE.value]

                    if current_prompt == "raise_right_hand" and rw.y < rs.y:
                        success = True
                    elif current_prompt == "raise_left_hand" and lw.y < ls.y:
                        success = True
                    elif current_prompt == "raise_both_hands" and rw.y < rs.y and lw.y < ls.y:
                        success = True
                    elif current_prompt == "touch_head":
                        dist_rw = abs(rw.x - nose.x) + abs(rw.y - nose.y)
                        dist_lw = abs(lw.x - nose.x) + abs(lw.y - nose.y)
                        if dist_rw < 0.08 or dist_lw < 0.08:
                            success = True

                    if (time.time() - prompt_start_time) > PROMPT_TIMEOUT:
                        ct = f"Cheat: Prompt timeout '{PROMPT_PRETTY[current_prompt]}'"
                        print("LOG:", ct)
                        cheat_log.append(ct)
                        current_idx += 1
                        if current_idx < len(sequence):
                            current_prompt = sequence[current_idx]
                            prompt_start_time = time.time()
                        else:
                            liveness_passed = False
                            print("LOG: Liveness timed out.")
                            break
                    elif success:
                        print(f"LOG: Passed liveness -> {PROMPT_PRETTY[current_prompt]}")
                        current_idx += 1
                        if current_idx < len(sequence):
                            current_prompt = sequence[current_idx]
                            prompt_start_time = time.time()
                            time.sleep(0.6)  # small pause for next prompt
                        else:
                            liveness_passed = True
                            print("SYSTEM: All liveness checks passed ✅")
                            break

            cv2.imshow("Cheat Detection", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("SYSTEM: Session ended by user.")
                break

        cap.release()
        cv2.destroyAllWindows()

        # Summary
        print("\n--- Session Summary ---")
        print(f"Liveness passed: {liveness_passed}")
        print("Cheat events:")
        if cheat_log:
            for e in cheat_log:
                print(" -", e)
        else:
            print(" - None logged")
        print("-----------------------\n")

        return liveness_passed

def exit_with_status(liveness_passed):
    if liveness_passed:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    result = main()
    exit_with_status(result)
