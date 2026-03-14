import cv2
import argparse
import mediapipe as mp
from body_part_angle import BodyPartAngle
from types_of_exercise import TypeOfExercise
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os

# ----------------------
# Arguments
# ----------------------
ap = argparse.ArgumentParser()
ap.add_argument("-t", "--exercise_type", type=str, required=True)
ap.add_argument("-u", "--user_id", type=str, required=True)
ap.add_argument("-vs", "--video_source", type=str, required=True)
args = vars(ap.parse_args())

# ----------------------
# Firebase init
# ----------------------
cred = credentials.Certificate("serviceAccountKey.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ----------------------
# Video capture
# ----------------------
mp_drawing = mp.solutions.drawing_utils
mp_pose = mp.solutions.pose

cap = cv2.VideoCapture(args["video_source"])
cap.set(3, 800)
cap.set(4, 480)

# ----------------------
# Exercise loop
# ----------------------
counter = 0
status = True

with mp_pose.Pose(min_detection_confidence=0.5,
                  min_tracking_confidence=0.5) as pose:

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame = cv2.resize(frame, (800, 480))
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        results = pose.process(frame_rgb)
        frame_rgb.flags.writeable = True
        frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

        try:
            landmarks = results.pose_landmarks.landmark
            counter, status = TypeOfExercise(landmarks).calculate_exercise(
                args["exercise_type"], counter, status)
        except:
            pass

        # render score table
        from utils import score_table
        frame = score_table(args["exercise_type"], frame, counter, status)

        mp_drawing.draw_landmarks(
            frame,
            results.pose_landmarks,
            mp_pose.POSE_CONNECTIONS,
            mp_drawing.DrawingSpec(color=(255, 255, 255), thickness=2, circle_radius=2),
            mp_drawing.DrawingSpec(color=(174, 139, 45), thickness=2, circle_radius=2),
        )

        cv2.imshow('Exercise', frame)
        if cv2.waitKey(10) & 0xFF == ord('q'):
            break

# ----------------------
# Save to Firebase
# ----------------------
db.collection("users").document(args["user_id"]).collection("exercises").add({
    "type": args["exercise_type"],
    "count": counter,
    "timestamp": datetime.now().isoformat()
})
print(f"Saved {counter} reps of {args['exercise_type']} for user {args['user_id']}")

cap.release()
cv2.destroyAllWindows()

# Optional: delete uploaded video to save space
if os.path.exists(args["video_source"]):
    os.remove(args["video_source"])
