# Land Use Change Detector

A web application for tracking environmental shifts and urbanization through interactive satellite imagery analysis.

## Overview
This project is a web application designed to monitor environmental changes using satellite imagery. It allows users to track land use alterations across specific regions over time.

## About
The application provides an interactive interface to analyze geospatial data. Users can select a region on a map and specify a time period. The system processes the satellite data to calculate changes in spectral indices. It displays the results using visual maps and statistical charts that show both the total area and the changed area.

## How to use
To use this application you must clone the repository and install the required dependencies.

1. Install the requirements using `pip install -r requirements.txt`.
2. Obtain a Google Earth Engine service account key and save it as a JSON file in the project directory.
3. Update the credentials path in `ee_engine.py` if necessary.
4. Run the backend server using `fastapi dev main.py`.
5. Open your web browser and navigate to the local server address to access the application.

## Why it was made
This project was developed to give researchers and environmentalists an accessible tool for monitoring ecological changes. Tracking land use change is essential to understand urbanization and environmental degradation. The application simplifies complex geospatial analysis and makes the data accessible to a wider audience.

## What are the sources
The application relies on data from Google Earth Engine. It specifically uses imagery from the Sentinel 2 and Landsat satellite programs.

## How the sources have been used
Google Earth Engine provides the computational power and data archive required for the analysis. The application requests satellite imagery for the selected dates and region. It applies spectral indices to the images and calculates the difference between the time periods. This difference highlights areas where significant land use change has occurred.

---

> *Note: This application including UI design, mapping logic and data integration was developed using modern AI assisted workflows with custom data integration, visualization design and project direction by the author.*
