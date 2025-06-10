# AppBrain Scraper

A Flask-based web application for scraping app data from AppBrain. This dashboard allows users to upload CSV files with package names, scrape data from AppBrain, view logs, export data, and search apps by developers.

## Features

- **Upload & Scrape**: Upload a CSV file with package names or enter them manually
- **App Dashboard**: View all scraped apps with details
- **Developer View**: See apps grouped by developers
- **Search**: Search apps by name, developer, or description
- **Export**: Export data in CSV, JSON, or Excel formats
- **Logs**: View scraping logs and job results

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd AppBrain-Scraper
   ```

2. Create a virtual environment and activate it:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

4. Configure the environment variables in the `.env` file (optional):
   ```
   # Application settings
   DEBUG=True
   SECRET_KEY=your_secret_key_here

   # Data storage settings
   DATA_DIR=data
   LOGS_DIR=logs
   EXPORTS_DIR=exports
   SCRAPED_DATA_DIR=scraped_data
   ```

## Usage

1. Start the application:
   ```
   python app.py
   ```

2. Open your web browser and navigate to `http://localhost:5000`

3. Use the dashboard to upload a CSV file with package names or enter them manually

4. View the scraped data in the Apps and Developers sections

5. Export the data in your preferred format

## CSV Format

The CSV file should have package names in the first column. Additional columns will be ignored.

Example:
```
com.example.app1
com.example.app2
com.example.app3
```

## Project Structure

```
├── app.py                 # Main application file
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
├── README.md              # This file
├── services/              # Service modules
│   ├── __init__.py        # Package initialization
│   ├── scraper.py         # Scraping functionality
│   └── data_manager.py    # Data management functionality
├── templates/             # HTML templates
│   ├── layout.html        # Base template
│   ├── index.html         # Dashboard homepage
│   ├── upload.html        # Upload & scrape page
│   ├── apps.html          # Apps listing page
│   ├── developers.html    # Developers listing page
│   ├── logs.html          # Logs page
│   └── export.html        # Export page
├── data/                  # Data storage (created at runtime)
├── logs/                  # Log files (created at runtime)
├── exports/               # Exported data (created at runtime)
├── scraped_data/          # Scraped HTML and JSON (created at runtime)
└── uploads/               # Uploaded CSV files (created at runtime)
```

## Dependencies

- Flask: Web framework
- Requests: HTTP library for making requests
- BeautifulSoup4: HTML parsing library
- Pandas: Data manipulation library
- Python-dotenv: Environment variable management
- Flask-WTF: Form handling

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for educational purposes only. Please respect AppBrain's terms of service and robots.txt when using this tool. Implement appropriate rate limiting and avoid excessive requests to prevent being blocked.