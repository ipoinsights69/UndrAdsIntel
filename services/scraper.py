import os
import json
import logging
import requests
import concurrent.futures
import time
from datetime import datetime
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning
import re

# Suppress only the single InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Configure logging
logger = logging.getLogger(__name__)

# Get environment variables
SCRAPER_API_KEY = os.getenv('SCRAPER_API_KEY')
SCRAPER_API_URL = os.getenv('SCRAPER_API_URL', 'http://api.scraperapi.com')
MAX_THREADS = int(os.getenv('MAX_THREADS', 1))
MAX_RETRIES = 2  # Maximum number of retries for failed requests


def make_request_with_retry(url, max_retries=MAX_RETRIES, timeout=15):
    """
    Make a request with retry logic for timeout and connection errors
    """
    payload = {'api_key': SCRAPER_API_KEY, 'url': url}
    
    for attempt in range(max_retries + 1):  # +1 because we want to include the initial attempt
        try:
            logger.info(f"Attempting request to {url} (attempt {attempt + 1}/{max_retries + 1})")
            response = requests.get('https://api.scraperapi.com/', params=payload, timeout=timeout)
            
            # If we get here, the request succeeded
            logger.info(f"Request successful for {url} on attempt {attempt + 1}")
            return response
            
        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout occurred for {url} on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s...
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Max retries ({max_retries}) reached for {url}")
                raise
                
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error for {url} on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Max retries ({max_retries}) reached for {url}")
                raise
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request exception for {url} on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries:
                wait_time = (attempt + 1) * 2  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Max retries ({max_retries}) reached for {url}")
                raise


def scrape_app_data(package_name, country='', category=''):
    print("corr")
    """
    Scrape app data from AppBrain for the given package name using ScraperAPI
    Includes optional country and category information
    """
    logger.info(f"Scraping data for package: {package_name}")
    
    # Construct the URL
    url = f"https://www.appbrain.com/app/body-color-swap/{package_name}"
    
    try:
        # Make request with retry logic
        response = make_request_with_retry(url)
        
        # Check if the request was successful
        if response.status_code != 200:
            logger.error(f"Failed to fetch data for {package_name}: HTTP {response.status_code}")
            return {
                "package_name": package_name,
                "status": "error",
                "error": f"HTTP Error: {response.status_code}",
                "timestamp": datetime.now().isoformat()
            }
        
        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Define target fields
        TARGET_FIELDS = {
            "Total downloads",
            "Recent downloads",
            "Rating",
            "Ranking",
            "APK size",
            "Designed for Android",
            "Suitable for",
            "Ads"
        }
        
        # Extract app name
        app_name = soup.find('title').get_text(strip=True) if soup.find('title') else "Unknown"
        
        # Extract table data
        table_data = {}
        for row in soup.select('table.table-striped tbody tr'):
            cells = row.find_all('td')
            if len(cells) == 2:
                key = cells[0].get_text(strip=True)
                if key in TARGET_FIELDS:
                    table_data[key] = cells[1].get_text(strip=True)
        
        # Extract developer information
        dev_name, dev_email, dev_website = None, None, None
        dev_section = next((s for s in soup.find_all("div", class_="app-section") if "Developer information" in s.get_text()), None)
        if dev_section:
            for a in dev_section.find_all("a", href=True):
                if a['href'].startswith("/dev/"): dev_name = a.get_text(strip=True)
                elif a['href'].startswith("mailto:"): dev_email = a.get_text(strip=True)
                elif a['href'].startswith("http"): dev_website = a['href']
        
        # Extract about section
        about_div = soup.find("div", class_="col-12 col-sm-6")

        if about_div:
            # Convert HTML to text and normalize spaces
            raw_text = about_div.get_text(separator=" ", strip=True)
            # Remove unnecessary multiple spaces and line breaks
            about_section_text = re.sub(r'\s+', ' ', raw_text).strip()
        else:
            about_div = soup.find("div", class_="col-12 col-sm-6")
            about_section_text = "\n".join(line.strip() for line in about_div.stripped_strings) if about_div else None
        
        # Extract app description
        desc_container = soup.select_one("a#descLink")
        cleaned_description = None
    
        if desc_container:
            raw_description = desc_container.get("data-contents")
            cleaned_description = BeautifulSoup(raw_description, "html.parser").get_text(separator="\n")
        else:
            print("Description not found.")
        
        # Fetch additional data using API calls with retry logic
        api_details = fetch_app_details(package_name)
        changelog_data = fetch_changelog(package_name)
        
        # Assemble final data object
        app_data = {
            "app_name": app_name,
            "package_name": package_name,
            **table_data,
            "developer_info": {
                "name": dev_name,
                "email": dev_email,
                "website": dev_website,
            },
            "about_section": about_section_text,
            "app_description": cleaned_description,
            "api_details": api_details,
            "changelog": changelog_data,
            "country": country,
            "category": category,
            "status": "success",
            "url": url,
            "timestamp": datetime.now().isoformat()
        }
        
        # Save the raw HTML for future processing if needed
        scraped_data_dir = os.getenv('SCRAPED_DATA_DIR', 'scraped_data')
        os.makedirs(scraped_data_dir, exist_ok=True)
        html_file = os.path.join(scraped_data_dir, f"{package_name}_raw.html")
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        # Save the extracted data
        data_file = os.path.join(scraped_data_dir, f"{package_name}.json")
        with open(data_file, 'w') as f:
            json.dump(app_data, f, indent=2)
        
        logger.info(f"Successfully scraped data for {package_name}")
        return app_data
        
    except Exception as e:
        logger.error(f"Error scraping {package_name}: {str(e)}")
        return {
            "package_name": package_name,
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def fetch_app_details(package_name):
    """
    Fetch additional app details (permissions, tech) from the main app_details page.
    This request is proxied through ScraperAPI with retry logic.
    """
    url = f"https://www.appbrain.com/app_details/{package_name}"

    try:
        # Make request with retry logic
        response = make_request_with_retry(url)
        logger.info(f"Status Code for {package_name}: {response.status_code}")
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # --- Extract Permissions ---
        api_permissions = {}
        permissions_section = soup.find("h2", string="Permissions")
        if permissions_section:
            permissions_div = permissions_section.find_next("div", class_="row app-permissions")
            if permissions_div:
                for perm_box in permissions_div.find_all("div", class_="default-box-color"):
                    perm_title = perm_box.find("b")
                    if perm_title:
                        title = perm_title.get_text(strip=True)
                        perm_div = perm_title.find_next_sibling("div")
                        perm_list = [p.strip() for p in perm_div.get_text().split(',') if p.strip()] if perm_div else []
                        api_permissions[title] = perm_list

        # --- Extract Technologies/Libraries ---
        api_technologies = {}
        tech_section = soup.find("h2", id="app-libraries")
        if tech_section:
            tech_row = tech_section.find_next("div", class_="row")
            if tech_row:
                for tech_col in tech_row.find_all("div", class_="col-sm-4"):
                    tech_title = tech_col.find("h3")
                    if tech_title:
                        category = tech_title.get_text(strip=True)
                        tech_list = [
                            lib_item.get_text(strip=True)
                            for lib_item in tech_col.find_all("a", class_="app-library-item")
                            if lib_item.get_text(strip=True)
                        ]
                        api_technologies[category] = tech_list

        return {
            "permissions": api_permissions,
            "technologies": api_technologies,
            "raw_html_snippet": response.text[:1000] + "..."  # Optional for debugging
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error while fetching API details for {package_name}: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Parsing error for {package_name}: {e}")
        return {"error": f"HTML parsing failed: {e}"}

def fetch_changelog(package_name):
    """
    Fetch and parse the app's changelog.
    This request is proxied through ScraperAPI with retry logic.
    """
    url = f"https://www.appbrain.com/app_details/{package_name}?changelog=true"
    changelog_entries = []

    logger.info(f"Fetching changelog for {package_name}...")
    try:
        # Make request with retry logic
        response = make_request_with_retry(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        changelog_ul = soup.find("ul", class_="app-changelog")
        if not changelog_ul:
            logger.warning(f"No changelog found for {package_name}")
            return []

        for li in changelog_ul.find_all("li"):
            date_tag = li.find("span", class_="date")
            type_tag = li.find("span", class_="type")
            desc_tag = li.find("span", class_="description")

            if date_tag and type_tag and desc_tag:
                entry = {
                    "date": date_tag.get_text(strip=True),
                    "type": type_tag.get_text(strip=True),
                    "description": desc_tag.get_text(strip=True)
                }
                changelog_entries.append(entry)

        return changelog_entries

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch changelog for {package_name}: {e}")
        return [{"error": str(e)}]
    except Exception as e:
        logger.error(f"Failed to parse changelog HTML for {package_name}: {e}")
        return [{"error": f"HTML parsing failed: {e}"}]


def scrape_multiple_apps(package_names):
    """
    Scrape data for multiple app package names using multi-threading
    """
    results = []
    
    logger.info(f"Starting multi-threaded scraping for {len(package_names)} apps with {MAX_THREADS} threads")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_package = {executor.submit(scrape_app_data, package_name): package_name for package_name in package_names}
        
        for future in concurrent.futures.as_completed(future_to_package):
            package_name = future_to_package[future]
            try:
                data = future.result()
                results.append(data)
                logger.info(f"Completed scraping for {package_name}")
            except Exception as e:
                logger.error(f"Exception occurred while scraping {package_name}: {str(e)}")
                results.append({
                    "package_name": package_name,
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })
    
    logger.info(f"Completed scraping for all {len(package_names)} apps")
    return results