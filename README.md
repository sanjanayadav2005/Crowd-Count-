# Crowd Count – People Counting Using Video Analytics

## 📌 Project Overview

This project aims to build a real-time people counting system using a live camera feed.  
The system will detect and track individuals in public areas such as malls, airports, and parks using computer vision and deep learning techniques.

It will provide:
- Live people count
- Zone-wise monitoring
- Heatmaps for density analysis
- Alerts for overcrowding
- Exportable analytics reports

---

## 🎯 Objectives

- Detect humans in a live video stream using YOLOv8
- Track individuals using DeepSORT / BYTETrack
- Count people entering, exiting, or present in defined zones
- Display real-time statistics on an interactive dashboard
- Maintain logs and export analytics data

---

## 🏗️ System Workflow

1. Capture live video from webcam/IP camera  
2. Extract frames from the video stream  
3. Detect people using YOLOv8  
4. Assign unique IDs for tracking  
5. Apply zone-based counting logic  
6. Store and visualize data  

---

## 🛠️ Tech Stack

- Python
- OpenCV
- YOLOv8 (Ultralytics)
- DeepSORT / BYTETrack
- Flask / Streamlit (for dashboard)
- SQLite / Firebase (for storage)

---

## 🚀 Milestone 1 (Current Progress)

- Project setup initialized
- Basic camera feed integration added
- Repository structure created

---

## ▶️ How to Run (Initial Setup)

```bash
pip install -r requirements.txt
python camera.py