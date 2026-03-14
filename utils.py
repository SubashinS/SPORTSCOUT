
import mediapipe as mp
import pandas as pd
import numpy as np
import cv2
from datetime import datetime, timedelta
from flask import request

mp_pose = mp.solutions.pose

def calculate_angle(a, b, c):
    a = np.array(a)  
    b = np.array(b)  
    c = np.array(c)  

    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) -\
              np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = np.abs(radians * 180.0 / np.pi)

    if angle > 180.0:
        angle = 360 - angle

    return angle



def detection_body_part(landmarks, body_part_name):
    return [
        landmarks[mp_pose.PoseLandmark[body_part_name].value].x,
        landmarks[mp_pose.PoseLandmark[body_part_name].value].y,
        landmarks[mp_pose.PoseLandmark[body_part_name].value].visibility
    ]


def detection_body_parts(landmarks):
    body_parts = pd.DataFrame(columns=["body_part", "x", "y"])

    for i, lndmrk in enumerate(mp_pose.PoseLandmark):
        lndmrk = str(lndmrk).split(".")[1]
        cord = detection_body_part(landmarks, lndmrk)
        body_parts.loc[i] = lndmrk, cord[0], cord[1]

    return body_parts


def score_table(exercise, frame , counter, status):
    cv2.putText(frame, "Activity : " + exercise.replace("-", " "),
                (10, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
                cv2.LINE_AA)
    cv2.putText(frame, "Counter : " + str(counter), (10, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "Status : " + str(status), (10, 135),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
    return frame

from datetime import datetime, timedelta

def get_daily_activity_summary(db, days=7):
    """
    Fetch daily activity counts for all users over the last `days`.
    Returns dict: { user_id: { date_str: count, ... }, ... }
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    activity_summary = {}

    users_ref = db.collection("users").stream()

    for user_doc in users_ref:
        user_id = user_doc.id
        user_activity = {}

        # Initialize counts per day
        for d in range(days):
            day = (start_date + timedelta(days=d)).date().isoformat()
            user_activity[day] = 0

        # Query exercises for user within date range
        exercises_ref = db.collection("users").document(user_id).collection("exercises") \
            .where("timestamp", ">=", start_date) \
            .where("timestamp", "<=", end_date).stream()

        for ex_doc in exercises_ref:
            ex_data = ex_doc.to_dict()
            ts = ex_data.get("timestamp")
            if not ts:
                continue
            date_str = ts.date().isoformat()
            count = ex_data.get("count", 1)  # Default to 1 if no count
            if date_str in user_activity:
                user_activity[date_str] += count

        activity_summary[user_id] = user_activity

    return activity_summary

def fetch_top_users(db, filters):
    users_ref = db.collection("users")
    # Apply filters if any (region, age, sport specialization)
    query = users_ref
    if filters.get("location"):
        query = query.where("location", "==", filters["location"])
    if filters.get("age"):
        query = query.where("age", "==", filters["age"])
    # Add other filter conditions similarly...

    top_users = []
    exercises = ["sit-up", "pull-up", "push-up", "squat", "walk", "vertical-jump"]
    for user_doc in query.stream():
        user_data = user_doc.to_dict()
        user_id = user_doc.id
        exercise_summary = {}
        for ex in exercises:
            ex_docs = db.collection("users").document(user_id).collection("exercises") \
                .where("type", "==", ex).stream()
            max_score = 0
            for ex_doc in ex_docs:
                e = ex_doc.to_dict()
                # Value depends on exercise type
                val = e.get("count", e.get("jump_height_cm", 0))
                if val > max_score:
                    max_score = val
            exercise_summary[ex] = max_score
        top_users.append({**user_data, **exercise_summary})
    # Sort by total score or define your ranking logic
    top_users.sort(key=lambda u: sum(u[ex] for ex in exercises if ex != "vertical-jump"), reverse=True)
    return top_users

def get_exercise_analytics(db, user_id, days=30):
    """
    Fetch exercise counts and progress for a single user over the past `days`.
    Returns a dict with exercise types as keys and a list of daily counts.
    """
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    # Prepare result structure
    exercises = ["sit-up", "pull-up", "push-up", "squat", "walk", "vertical-jump"]
    analytics = {ex: [0]*days for ex in exercises}

    # Query exercises collection for user filtered by date range
    ex_collection = db.collection("users").document(user_id).collection("exercises") \
        .where("timestamp", ">=", start_date) \
        .where("timestamp", "<=", end_date).stream()

    for ex_doc in ex_collection:
        ex_data = ex_doc.to_dict()
        ex_type = ex_data.get("type")
        ts = ex_data.get("timestamp")
        if ex_type not in exercises or ts is None:
            continue

        day_index = (ts.date() - start_date.date()).days
        count = ex_data.get("count", 1)
        # Sum counts per day per exercise
        if 0 <= day_index < days:
            analytics[ex_type][day_index] += count

    return analytics

def get_comparative_insights(db, group_by="location"):
    """
    Compares average exercise performance metrics by group (location, age, etc.).
    Returns a dict of groups with average scores.
    """
    users_ref = db.collection("users")
    groups = {}

    for user_doc in users_ref.stream():
        user_data = user_doc.to_dict()
        group_key = user_data.get(group_by, "Unknown")
        if group_key not in groups:
            groups[group_key] = {"total_score": 0, "count": 0}

        user_id = user_doc.id
        exercises = ["sit-up", "pull-up", "push-up", "squat", "walk", "vertical-jump"]
        total_score = 0

        for ex in exercises:
            ex_docs = db.collection("users").document(user_id).collection("exercises") \
                      .where("type", "==", ex).stream()
            max_val = 0
            for ex_doc in ex_docs:
                val = ex_doc.to_dict().get("count", ex_doc.to_dict().get("jump_height_cm", 0))
                if val > max_val:
                    max_val = val
            # Sum except for vertical-jump if needed or adapt logic
            if ex != "vertical-jump":
                total_score += max_val

        groups[group_key]["total_score"] += total_score
        groups[group_key]["count"] += 1

    # Compute averages
    for k in groups:
        groups[k]["avg_score"] = groups[k]["total_score"] / max(groups[k]["count"], 1)

    return groups


    
