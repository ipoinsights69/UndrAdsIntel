import os
import json
import csv
import io
import uuid
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import re

import os

RESULTS_DIR = "results"

def delete_job_by_id(job_id):
    job_file = os.path.join(RESULTS_DIR, f"{job_id}.json")
    
    if os.path.exists(job_file):
        os.remove(job_file)
    else:
        raise FileNotFoundError(f"No results file found for job ID: {job_id}")

# Load environment variables
load_dotenv()

# Configure logging
log_dir = os.getenv('LOGS_DIR', 'logs')
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create necessary directories
for directory in ['data', 'logs', 'exports', 'scraped_data', 'uploads']:
    os.makedirs(os.path.join(os.getcwd(), directory), exist_ok=True)

# Global dictionary to track scraping jobs
scraping_jobs = {}

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'csv'}

# Import services after app initialization to avoid circular imports
from services.scraper import scrape_app_data, scrape_multiple_apps, fetch_app_details, fetch_changelog
# Import data_manager module instead of individual functions
import services.data_manager as data_manager


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@app.route('/')
def index():
    # Get statistics for dashboard
    try:
        stats = {
            'total_apps': len(data_manager.get_all_apps()),
            'total_developers': len(set(app.get('developer_info', {}).get('name', '') for app in data_manager.get_all_apps())),
            'recent_scrapes': 0  # This would be implemented with a proper tracking system
        }
    except Exception as e:
        logging.error(f"Error getting stats: {str(e)}")
        stats = {
            'total_apps': 0,
            'total_developers': 0,
            'recent_scrapes': 0
        }
    return render_template('index.html', stats=stats)


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'csv_file' in request.files:
            file = request.files['csv_file']
            if file.filename == '':
                flash('No file selected', 'error')
                return redirect(request.url)
            
            if file and allowed_file(file.filename):
                # Read package names from CSV
                package_names = []
                try:
                    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                    csv_reader = csv.reader(stream)
                    for row in csv_reader:
                        if row and row[0].strip():  # Check if row is not empty
                            package_names.append(row[0].strip())
                except Exception as e:
                    flash(f'Error reading CSV file: {str(e)}', 'error')
                    return redirect(request.url)
                
                if not package_names:
                    flash('No package names found in the CSV file', 'error')
                    return redirect(request.url)
                
                # Get country and category from form
                country = request.form.get('country', '')
                category = request.form.get('category', '')
                
                # Create a unique job ID
                job_id = str(uuid.uuid4())
                
                # Store job information
                scraping_jobs[job_id] = {
                    'package_names': package_names,
                    'total': len(package_names),
                    'completed': 0,
                    'status': 'running',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'country': country,
                    'category': category
                }
                
                # Start scraping in a separate thread
                threading.Thread(
                    target=scrape_and_save,
                    args=(package_names, job_id, None, 'all', country, category),
                    daemon=True
                ).start()
                
                flash(f'Started scraping {len(package_names)} apps. Job ID: {job_id}', 'success')
                return redirect(url_for('logs'))
            else:
                flash('Only CSV files are allowed', 'error')
                return redirect(request.url)
        
        # Handle manual package name input
        elif 'package_names' in request.form:
            package_names_text = request.form['package_names']
            if not package_names_text.strip():
                flash('No package names entered', 'error')
                return redirect(request.url)
            
            # Split by newline and clean up
            package_names = [name.strip() for name in package_names_text.split('\n') if name.strip()]
            
            if not package_names:
                flash('No valid package names entered', 'error')
                return redirect(request.url)
            
            # Get country and category from form
            country = request.form.get('country', '')
            category = request.form.get('category', '')
            
            # Create a unique job ID
            job_id = str(uuid.uuid4())
            
            # Store job information
            scraping_jobs[job_id] = {
                'package_names': package_names,
                'total': len(package_names),
                'completed': 0,
                'status': 'running',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'country': country,
                'category': category
            }
            
            # Start scraping in a separate thread
            threading.Thread(
                target=scrape_and_save,
                args=(package_names, job_id, None, 'all', country, category),
                daemon=True
            ).start()
            
            flash(f'Started scraping {len(package_names)} apps. Job ID: {job_id}', 'success')
            return redirect(url_for('logs'))
        
        else:
            flash('No file or package names provided', 'error')
            return redirect(request.url)
    
    return render_template('upload.html')


@app.route('/apps')
def apps():
    search_query = request.args.get('search', '')
    developer = request.args.get('developer', '')
    
    if search_query:
        apps_list = data_manager.search_apps(search_query)
    elif developer:
        apps_list = data_manager.get_apps_by_developer(developer)
    else:
        apps_list = data_manager.get_all_apps()
    
    return render_template('apps.html', apps=apps_list, search_query=search_query, developer=developer)


@app.route('/developers')
def developers():
    all_apps = data_manager.get_all_apps()
    developers_dict = {}
    
    for app_data in all_apps:
        dev = app_data.get('developer_info', {}).get('name', 'Unknown')
        if dev not in developers_dict:
            developers_dict[dev] = []
        developers_dict[dev].append(app_data)
    
    return render_template('developers.html', developers=developers_dict)


@app.route('/logs')
def logs():
    # Get the last 200 lines of the log file and parse them
    log_file = os.path.join(log_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log')
    log_entries = []
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-200:] if len(all_lines) > 200 else all_lines
            for line in last_lines:
                try:
                    # Parse log line format: timestamp - name - level - message
                    parts = line.strip().split(' - ', 3)
                    if len(parts) >= 4:
                        log_entries.append({
                            'timestamp': parts[0],
                            'name': parts[1],
                            'level': parts[2],
                            'message': parts[3]
                        })
                except Exception as e:
                    app.logger.error(f"Error parsing log line: {str(e)}")
                    continue
    
    # Get all job results
    jobs = []
    results_dir = os.path.join(app.root_path, 'results')
    if os.path.exists(results_dir):
        for filename in os.listdir(results_dir):
            if filename.endswith('.json'):
                job_id = filename.replace('.json', '')
                job_file = os.path.join(results_dir, filename)
                
                try:
                    with open(job_file, 'r') as f:
                        job_data = json.load(f)
                        
                        # Get job status from scraping_jobs if available
                        status = 'complete'  # Default status for old jobs
                        progress = 100  # Default progress for old jobs
                        if job_id in scraping_jobs:
                            status = scraping_jobs[job_id]['status']
                            total = scraping_jobs[job_id]['total']
                            completed = scraping_jobs[job_id]['completed']
                            progress = int((completed / total) * 100) if total > 0 else 0
                        
                        # Calculate stats
                        results = job_data.get('results', {})
                        total_apps = len(results)
                        success_count = sum(1 for app in results.values() if app.get('status') == 'success')
                        failed_count = sum(1 for app in results.values() if app.get('status') == 'error')
                        partial_count = sum(1 for app in results.values() 
                                         if app.get('status') == 'partial')
                        
                        # Add job to list with additional info
                        job_info = {
                            'job_id': job_id,
                            'timestamp': job_data.get('timestamp', ''),
                            'status': status,
                            'progress': progress,
                            'success_count': success_count,
                            'failed_count': failed_count,
                            'partial_count': partial_count,
                            'completed_apps': completed,  # Make sure this is included
                            'total_apps': total           # Make sure this is included
                        }
                        jobs.append(job_info)
    
                except Exception as e:
                    app.logger.error(f"Error loading job data: {str(e)}")
                    continue
                
    # Sort jobs by timestamp (newest first)
    jobs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Get active jobs that might not have results yet
    for job_id, job_info in scraping_jobs.items():
        if job_info['status'] == 'running':
            # Check if job is already in the list
            if not any(job['job_id'] == job_id for job in jobs):
                total = job_info.get('total', 0)
                completed = job_info.get('completed', 0)
                progress = int((completed / total) * 100) if total > 0 else 0
                
                jobs.append({
                    'job_id': job_id,
                    'timestamp': job_info.get('timestamp', ''),
                    'total_apps': total,
                    'success_count': 0,  # We don't know yet
                    'failed_count': 0,   # We don't know yet
                    'partial_count': 0,  # We don't know yet
                    'status': 'running',
                    'progress': progress,
                    'completed_apps': completed,
                    'original_job_id': job_info.get('original_job_id', ''),
                    'retry_mode': job_info.get('retry_mode', 'all')
                })
    
    return render_template('logs.html', jobs=jobs, log_content=log_entries)

@app.route('/view_job_results/<job_id>')
def view_job_results(job_id):
    # Get job results
    file_path = os.path.join(app.root_path, 'results', f"{job_id}.json")
    if not os.path.exists(file_path):
        flash('Job results not found', 'error')
        return redirect(url_for('logs'))
    
    try:
        with open(file_path, 'r') as f:
            job_data = json.load(f)
        
        # Extract the actual results which is a dictionary with package names as keys
        results = job_data.get('results', {})
        timestamp = datetime.fromisoformat(job_data.get('timestamp', datetime.now().isoformat()))
        package_names = job_data.get('package_names', [])
        
        # Initialize variables with default values
        completed = 0
        total = len(package_names) if package_names else 0
        
        # Process app results
        success_apps = []
        failed_apps = []
        partial_success = []
        
        # Iterate through the results dictionary
        for package_name, app_data in results.items():
            # Skip if app_data is not a dictionary
            if not isinstance(app_data, dict):
                app.logger.warning(f"Skipping non-dict app_data for {package_name}: {type(app_data)}")
                continue
                
            # Add package_name to the app_data dictionary for easier access in template
            app_data['package_name'] = package_name
            
            # Categorize based on status or presence of data
            if app_data.get('status') == 'error':
                failed_apps.append(app_data)
            elif not app_data.get('api_details') or not app_data.get('changelog'):
                partial_success.append(app_data)
            else:
                success_apps.append(app_data)
        
        # Get job status and progress
        job_status = scraping_jobs.get(job_id, {})
        is_running = job_status.get('status') == 'running'
        
        # Calculate completed count based on job status
        if is_running:
            # For running jobs, get completed count from scraping_jobs
            completed = job_status.get('completed', 0)
            total = job_status.get('total', total)  # Use the total from job_status if available
        else:
            # For completed jobs, calculate from results
            completed = len(success_apps) + len(failed_apps) + len(partial_success)
        
        # Calculate stats - ensure all values are defined
        stats = {
            'total': total,
            'success': len(success_apps),
            'failed': len(failed_apps),
            'partial': len(partial_success),
            'completed': completed  # Explicitly include completed count
        }
        
        # Combine all apps for the all_apps tab
        all_apps = success_apps + failed_apps + partial_success
        
        app.logger.info(f"Job {job_id} stats: {stats}")
        
        return render_template('job_results.html', 
                              job_id=job_id,
                              timestamp=timestamp,
                              results=results,
                              all_apps=all_apps,
                              success_apps=success_apps,
                              failed_apps=failed_apps,
                              partial_success=partial_success,
                              stats=stats)
    except Exception as e:
        app.logger.error(f"Error loading job results {job_id}: {str(e)}")
        flash(f'Error loading job results: {str(e)}', 'error')
        return redirect(url_for('logs'))


@app.route('/stop_job/<job_id>', methods=['POST'])
def stop_job(job_id):
    if job_id in scraping_jobs:
        scraping_jobs[job_id]['status'] = 'stopped'
        return jsonify({
            'status': 'success',
            'message': f'Job {job_id} has been stopped'
        })
    return jsonify({
        'status': 'error',
        'message': f'Job {job_id} not found'
    })

@app.route('/retry_failed_apps/<job_id>', methods=['GET', 'POST'])
def retry_failed_apps(job_id):
    # Load job data
    job_file = os.path.join(app.root_path, 'results', f'{job_id}.json')
    if not os.path.exists(job_file):
        flash(f'Job results not found for job ID: {job_id}', 'error')
        return redirect(url_for('logs'))
    
    with open(job_file, 'r') as f:
        job_data = json.load(f)
    
    timestamp = job_data.get('timestamp', '')
    results = job_data.get('results', {})
    
    if request.method == 'GET':
        # Categorize failed apps
        failed_apps = []
        missing_details_apps = []
        missing_changelog_apps = []
        
        for package_name, app_data in results.items():
            # Check for complete failures
            if app_data.get('status') == 'error':
                failed_apps.append({
                    'package_name': package_name,
                    'error': app_data.get('error', 'Unknown error')
                })
            else:
                # Check for missing details
                if not app_data.get('api_details') or not app_data.get('api_details', {}).get('permissions'):
                    missing_details_apps.append({
                        'package_name': package_name,
                        'error': 'Missing API details'
                    })
                
                # Check for missing changelog
                if not app_data.get('changelog'):
                    missing_changelog_apps.append({
                        'package_name': package_name,
                        'error': 'Missing changelog'
                    })
        
        return render_template(
            'retry_failed.html',
            job_id=job_id,
            timestamp=timestamp,
            failed_apps=failed_apps,
            missing_details_apps=missing_details_apps,
            missing_changelog_apps=missing_changelog_apps
        )
    
    elif request.method == 'POST':
        retry_type = request.form.get('retry_type', 'all')
        package_names = []
        
        if retry_type == 'all':
            # Retry all failed apps
            for package_name, app_data in results.items():
                if app_data.get('status') == 'error':
                    package_names.append(package_name)
        
        elif retry_type == 'details':
            # Retry apps with missing details
            for package_name, app_data in results.items():
                if not app_data.get('api_details') or not app_data.get('api_details', {}).get('permissions'):
                    package_names.append(package_name)
        
        elif retry_type == 'changelog':
            # Retry apps with missing changelog
            for package_name, app_data in results.items():
                if not app_data.get('changelog'):
                    package_names.append(package_name)
        
        if not package_names:
            return jsonify({
                'status': 'error',
                'message': 'No apps to retry'
            })
        
        # Create a new job ID for the retry
        new_job_id = str(uuid.uuid4())
        
        # Store job information
        scraping_jobs[new_job_id] = {
            'package_names': package_names,
            'total': len(package_names),
            'completed': 0,
            'status': 'running',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'original_job_id': job_id,
            'retry_mode': retry_type
        }
        
        # Start scraping in a separate thread
        threading.Thread(
            target=scrape_and_save,
            args=(package_names, new_job_id, job_id, retry_type),
            daemon=True
        ).start()
        
        return jsonify({
            'status': 'success',
            'message': f'Started retrying {len(package_names)} apps',
            'job_id': new_job_id,
            'redirect_url': url_for('logs')
        })

def scrape_and_save(package_names, job_id, original_job_id=None, retry_mode='all', country='', category=''):
    """Scrape apps and save results, with support for retrying specific parts and country/category info"""
    results = {}
    total_apps = len(package_names)
    
    # If we're retrying details or changelog, load the original data
    original_data = {}
    if original_job_id and retry_mode in ['details', 'changelog']:
        original_file = os.path.join(app.root_path, 'results', f'{original_job_id}.json')
        if os.path.exists(original_file):
            try:
                with open(original_file, 'r') as f:
                    original_data = json.load(f)
                    # Extract results from the structure
                    if 'results' in original_data:
                        original_data = original_data['results']
            except Exception as e:
                logging.error(f"Error loading original job data: {str(e)}")
    
    # Scrape each app
    for i, package_name in enumerate(package_names):
        # Check if job has been stopped
        if job_id in scraping_jobs and scraping_jobs[job_id].get('status') == 'stopped':
            logging.info(f"[Job {job_id}] Stopping job as requested by user after processing {i} apps")
            break
            
        try:
            logging.info(f"[Job {job_id}] Scraping {i+1}/{total_apps}: {package_name}")
            
            if retry_mode == 'all':
                # Full scrape
                app_data = scrape_app_data(package_name, country, category)
                results[package_name] = app_data
            
            elif retry_mode == 'details':
                # Only retry app details
                if package_name in original_data:
                    # Start with the original data
                    app_data = original_data[package_name]
                    
                    # Fetch just the app details
                    try:
                        app_details = fetch_app_details(package_name)
                        
                        # Update the app data with new details
                        app_data['api_details'] = app_details
                        app_data['status'] = 'success'
                        app_data['error'] = ''
                    except Exception as e:
                        logging.error(f"[Job {job_id}] Error fetching details for {package_name}: {str(e)}")
                        app_data['error'] = f"Error fetching details: {str(e)}"
                    
                    results[package_name] = app_data
                else:
                    # If original data not found, do a full scrape
                    logging.warning(f"[Job {job_id}] Original data not found for {package_name}, doing full scrape")
                    app_data = scrape_app_data(package_name, country, category)
                    results[package_name] = app_data
            
            elif retry_mode == 'changelog':
                # Only retry changelog
                if package_name in original_data:
                    # Start with the original data
                    app_data = original_data[package_name]
                    
                    # Fetch just the changelog
                    try:
                        changelog = fetch_changelog(package_name)
                        
                        # Update the app data with new changelog
                        app_data['changelog'] = changelog
                        app_data['status'] = 'success'
                        app_data['error'] = ''
                    except Exception as e:
                        logging.error(f"[Job {job_id}] Error fetching changelog for {package_name}: {str(e)}")
                        app_data['error'] = f"Error fetching changelog: {str(e)}"
                    
                    results[package_name] = app_data
                else:
                    # If original data not found, do a full scrape
                    logging.warning(f"[Job {job_id}] Original data not found for {package_name}, doing full scrape")
                    app_data = scrape_app_data(package_name, country, category)
                    results[package_name] = app_data
        
        except Exception as e:
            logging.error(f"[Job {job_id}] Error scraping {package_name}: {str(e)}")
            results[package_name] = {
                'package_name': package_name,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        
        # Update job status
        if job_id in scraping_jobs:
            scraping_jobs[job_id]['completed'] = i + 1
    
    # Save results to file
    output = {
        'job_id': job_id,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'package_names': package_names,
        'country': country,
        'category': category,
        'results': results
    }
    
    results_dir = os.path.join(app.root_path, 'results')
    os.makedirs(results_dir, exist_ok=True)
    results_file = os.path.join(results_dir, f'{job_id}.json')
    
    with open(results_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    # Update job status - only change to 'complete' if not already 'stopped'
    if job_id in scraping_jobs and scraping_jobs[job_id].get('status') != 'stopped':
        scraping_jobs[job_id]['status'] = 'complete'
        # Store the new job ID in the original job for reference
        if original_job_id and original_job_id in scraping_jobs:
            scraping_jobs[original_job_id]['new_job_id'] = job_id
    
    logging.info(f"[Job {job_id}] Scraping complete. Results saved to {results_file}")


@app.route('/export', methods=['GET', 'POST'])
def export():
    if request.method == 'POST':
        export_format = request.form.get('format', 'csv')
        
        # Collect all filter parameters
        filters = {}
        
        # Ads filter
        if 'ads_filter' in request.form and request.form['ads_filter']:
            filters['ads_filter'] = request.form['ads_filter']
        
        # Ranking filter
        if 'ranking_filter' in request.form and request.form['ranking_filter']:
            filters['ranking_filter'] = request.form['ranking_filter']
        
        # APK size filter
        if 'apk_size_min' in request.form and request.form['apk_size_min']:
            filters['apk_size_min'] = request.form['apk_size_min']
        if 'apk_size_max' in request.form and request.form['apk_size_max']:
            filters['apk_size_max'] = request.form['apk_size_max']
        
        # Total downloads filter
        if 'total_downloads_min' in request.form and request.form['total_downloads_min']:
            filters['total_downloads_min'] = request.form['total_downloads_min']
            if 'total_downloads_min_unit' in request.form:
                filters['total_downloads_min_unit'] = request.form['total_downloads_min_unit']
        
        # Recent downloads filter
        if 'recent_downloads_min' in request.form and request.form['recent_downloads_min']:
            filters['recent_downloads_min'] = request.form['recent_downloads_min']
            if 'recent_downloads_min_unit' in request.form:
                filters['recent_downloads_min_unit'] = request.form['recent_downloads_min_unit']
        
        # Android version filter
        if 'android_version_min' in request.form and request.form['android_version_min']:
            filters['android_version_min'] = request.form['android_version_min']
        
        # Rating filter (new)
        if 'rating_min' in request.form and request.form['rating_min']:
            filters['rating_min'] = request.form['rating_min']
        if 'rating_max' in request.form and request.form['rating_max']:
            filters['rating_max'] = request.form['rating_max']
        
        # Developer filter
        if 'developer' in request.form and request.form['developer']:
            filters['developer'] = request.form['developer']
        
        # Country filter
        if 'country_filter' in request.form and request.form['country_filter']:
            filters['country_filter'] = request.form['country_filter']
        
        # Category filter
        if 'category_filter' in request.form and request.form['category_filter']:
            filters['category_filter'] = request.form['category_filter']
        
        # Export options
        if 'include_all_technologies' in request.form:
            filters['include_all_technologies'] = request.form['include_all_technologies']
        if 'include_latest_changelog' in request.form:
            filters['include_latest_changelog'] = request.form['include_latest_changelog']
        
        try:
            # Get export name if provided
            export_name = request.form.get('export_name', '')
            
            # Call the export_data function with filters and export name
            filename = data_manager.export_data(export_format, filters, export_name)
            
            if filename:
                flash(f'Data exported successfully as {export_format.upper()}', 'success')
                return redirect(url_for('export'))
            else:
                flash('No data to export', 'warning')
                return redirect(url_for('export'))
        except Exception as e:
            app.logger.error(f"Export error: {str(e)}")
            flash(f'Error exporting data: {str(e)}', 'danger')
            return redirect(url_for('export'))
    
    # GET request - show export page with history
    export_files = []
    exports_dir = os.path.join(app.root_path, 'exports')
    
    if os.path.exists(exports_dir):
        for filename in os.listdir(exports_dir):
            if os.path.isfile(os.path.join(exports_dir, filename)):
                file_path = os.path.join(exports_dir, filename)
                file_stats = os.stat(file_path)
                
                # Determine format from filename
                if filename.endswith('.csv'):
                    format_type = 'CSV'
                elif filename.endswith('.json'):
                    format_type = 'JSON'
                elif filename.endswith('.xlsx'):
                    format_type = 'Excel'
                else:
                    format_type = 'Unknown'
                
                # Format file size
                size_bytes = file_stats.st_size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} bytes"
                elif size_bytes < 1024 * 1024:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                else:
                    size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                
                export_files.append({
                    'filename': filename,
                    'format': format_type,
                    'date': datetime.fromtimestamp(file_stats.st_mtime),
                    'size': size_str
                })
    
    # Sort files by date (newest first)
    export_files.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('export.html', export_files=export_files)


@app.route('/download/<filename>')
def download_file(filename):
    """Download an exported file."""
    # Validate filename to prevent directory traversal
    if not re.match(r'^[\w\-\.]+$', filename):
        flash('Invalid filename', 'danger')
        return redirect(url_for('export'))
    
    # Set the exports directory path
    exports_dir = os.path.join(app.root_path, 'exports')
    
    # Check if file exists
    file_path = os.path.join(exports_dir, filename)
    if not os.path.isfile(file_path):
        flash('File not found', 'danger')
        return redirect(url_for('export'))
    
    # Determine content type based on file extension
    content_type = None
    if filename.endswith('.csv'):
        content_type = 'text/csv'
    elif filename.endswith('.json'):
        content_type = 'application/json'
    elif filename.endswith('.xlsx'):
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    # Send the file with appropriate content type
    return send_file(
        file_path,
        mimetype=content_type,
        as_attachment=True,
        download_name=filename
    )


@app.route('/api/apps')
def api_apps():
    return jsonify(get_all_apps())


@app.route('/api/apps/search')
def api_search_apps():
    query = request.args.get('q', '')
    return jsonify(search_apps(query))


@app.route('/api/apps/developer/<developer>')
def api_apps_by_developer(developer):
    return jsonify(get_apps_by_developer(developer))


# Custom Jinja2 filters
@app.template_filter('exists')
def file_exists(path):
    return os.path.exists(path)

@app.template_filter('listdir')
def list_directory(path):
    if os.path.exists(path):
        return os.listdir(path)
    return []


@app.route('/api/scraping/status')
def get_scraping_status():
    """API endpoint to get the status of a scraping job"""
    job_id = request.args.get('job_id')
    if not job_id or job_id not in scraping_jobs:
        return jsonify({
            'error': 'Invalid job ID',
            'status': 'error'
        }), 400
    
    job_data = scraping_jobs[job_id]
    
    # Calculate progress percentage
    total = job_data.get('total_apps', 0)
    completed = job_data.get('completed_apps', 0)
    
    # Get the last 20 log lines related to this job
    log_lines = []
    try:
        log_file = os.path.join('logs', f"{datetime.now().strftime('%Y-%m-%d')}.log")
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = f.readlines()
                # Filter logs for this job and get the last 20 lines
                job_logs = [log for log in logs if job_id in log]
                log_lines = ''.join(job_logs[-20:]) if job_logs else 'No logs available for this job.'
    except Exception as e:
        log_lines = f"Error reading logs: {str(e)}"
    
    return jsonify({
        'status': job_data.get('status', 'running'),
        'total': total,
        'completed': completed,
        'logs': log_lines,
        'job_id': job_id
    })


@app.route('/delete-job/<job_id>', methods=['POST'])
def delete_job(job_id):
    try:
        # Your logic here to delete the job from DB or job store
        delete_job_by_id(job_id)  # <-- implement this function based on your backend
        flash(f"Job {job_id} deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting job {job_id}: {str(e)}", "error")
    return redirect(url_for('logs'))

@app.route('/api/logs')
def api_logs():
    level = request.args.get('level', 'all')
    log_file = os.path.join(log_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log')
    logs = []
    
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            # Only get the last 200 lines for fresh logs
            all_lines = f.readlines()
            recent_lines = all_lines[-200:] if len(all_lines) > 200 else all_lines
            
            # Filter by level if specified
            if level != 'all':
                filtered_lines = []
                for line in recent_lines:
                    if f' - {level.upper()} - ' in line:
                        filtered_lines.append(line)
                logs = ''.join(filtered_lines)
            else:
                logs = ''.join(recent_lines)
    
    return jsonify({'logs': logs})


# Add static route
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


@app.route('/app/<package_name>')
def app_details(package_name):
    # Find the app data in the scraped_data directory
    app_file_path = os.path.join(app.root_path, 'scraped_data', f'{package_name}.json')
    
    if not os.path.exists(app_file_path):
        flash(f'App data not found for {package_name}', 'error')
        return redirect(url_for('apps'))
    
    try:
        with open(app_file_path, 'r') as f:
            app_data = json.load(f)
        
        # Add package_name to the app data if not already present
        if 'package_name' not in app_data:
            app_data['package_name'] = package_name
            
        return render_template('app_details.html', app=app_data)
    except Exception as e:
        app.logger.error(f"Error loading app data for {package_name}: {str(e)}")
        flash(f'Error loading app data: {str(e)}', 'error')
        return redirect(url_for('apps'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Get credentials from .env file
        admin_username = os.getenv('ADMIN_USERNAME')
        admin_password = os.getenv('ADMIN_PASSWORD')
        
        # Check if credentials are set in .env
        if not admin_username or not admin_password:
            flash('Admin credentials not configured. Please set ADMIN_USERNAME and ADMIN_PASSWORD in .env file.', 'error')
            return redirect(url_for('login'))
        
        # Validate credentials
        if username == admin_username and password == admin_password:
            session['logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('login'))
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))


@app.route('/edit_env', methods=['GET', 'POST'])
def edit_env():
    # Check if user is logged in
    if not session.get('logged_in'):
        flash('You must be logged in to access this page', 'error')
        return redirect(url_for('login'))
    
    env_file_path = os.path.join(os.getcwd(), '.env')
    
    if request.method == 'POST':
        # Get form data
        env_vars = {}
        for key, value in request.form.items():
            # Skip empty values except for password which can be empty to keep current password
            if value or key == 'ADMIN_PASSWORD':
                env_vars[key] = value
        
        # Handle password separately
        if not env_vars.get('ADMIN_PASSWORD'):
            # If password field is empty, keep the current password
            env_vars['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', '')
        
        # Write to .env file
        with open(env_file_path, 'w') as f:
            for key, value in env_vars.items():
                if key == 'CUSTOM_SCRIPT':
                    # For script content, encode as a single line
                    encoded_value = value.replace('\n', '\\n').replace('\r', '\\r')
                    f.write(f"{key}={encoded_value}\n")
                else:
                    f.write(f"{key}={value}\n")
        
        # Reload environment variables
        load_dotenv(override=True)
        
        flash('Environment variables updated successfully', 'success')
        return redirect(url_for('edit_env'))
    
    # Read current .env file
    env_vars = {}
    if os.path.exists(env_file_path):
        with open(env_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        key, value = line.split('=', 1)
                        # Handle special case for CUSTOM_SCRIPT
                        if key == 'CUSTOM_SCRIPT':
                            # Decode escaped newlines and carriage returns
                            value = value.replace('\\n', '\n').replace('\\r', '\r')
                        env_vars[key] = value
                    except ValueError:
                        # Skip lines that don't have a key=value format
                        logging.warning(f"Skipping invalid line in .env file: {line}")
                        continue
    
    return render_template('edit_env.html', env_vars=env_vars)


# Add login_required decorator function
def login_required(view_function):
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('You must be logged in to access this page', 'error')
            return redirect(url_for('login'))
        return view_function(*args, **kwargs)
    decorated_function.__name__ = view_function.__name__
    return decorated_function


# @app.route('/api/stop-job/<job_id>', methods=['POST'])
# def stop_job(job_id):
#     """API endpoint to stop a running job"""
#     if not job_id or job_id not in scraping_jobs:
#         return jsonify({
#             'error': 'Invalid job ID',
#             'status': 'error'
#         }), 400
    
    # Mark the job as stopped
    scraping_jobs[job_id]['status'] = 'stopped'
    logging.info(f"[Job {job_id}] Job manually stopped by user")
    
    return jsonify({
        'status': 'success',
        'message': f'Job {job_id} has been stopped'
    })


if __name__ == '__main__':
    print("Starting AppBrain Scraper...")
    print(f"App running in {os.getcwd()}")
    print(f"Debug mode: {os.getenv('DEBUG', 'True')}")
    print(f"ScraperAPI Key: {'Configured' if os.getenv('SCRAPER_API_KEY') else 'Not configured'}")
    print(f"Max Threads: {os.getenv('MAX_THREADS', '5')}")
    app.run(debug=os.getenv('DEBUG', 'True') == 'True', host='0.0.0.0', port=1234)