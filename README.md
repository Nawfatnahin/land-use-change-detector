# Land Use Change Detector

## Overview
This project is a web application designed to monitor environmental shifts using satellite imagery. It allows users to track land use change across specific regions over time.

## About
The application provides an interactive interface for analyzing geospatial data. Users can draw a region on a map and specify a time period. The system then processes satellite data to calculate changes in spectral indices. It displays the results through visual maps and statistical charts showing total area and changed area.

## How to use
To use this application you must clone the repository and install the required dependencies.

1. Install the requirements using `pip install -r requirements.txt`.
2. Obtain a Google Earth Engine service account key and save it as a JSON file in the project directory.
3. Update the credentials path in `ee_engine.py` if necessary.
4. Run the backend server using `fastapi dev main.py`.
5. Open your web browser and navigate to the local server address to access the application.

## Why it was made
This project was developed to provide researchers and environmentalists with an accessible tool for monitoring ecological changes. Tracking land use change is essential for understanding urbanization and environmental degradation. The application simplifies complex geospatial analysis and makes the data accessible to a wider audience.

## What are the sources
The application relies on data from Google Earth Engine. It specifically utilizes imagery from Sentinel 2 and Landsat satellite programs.

## How the sources have been used
Google Earth Engine provides the computational power and data archive required for the analysis. The application requests satellite imagery for the selected dates and region. It then applies spectral indices to the images and calculates the difference between the time periods. This difference highlights areas where significant land use change has occurred.

---

## Note: This application, including UI design, mapping logic and data integration was developed using modern AI-assisted workflows with custom data integration, visualization design and project direction by the author.
