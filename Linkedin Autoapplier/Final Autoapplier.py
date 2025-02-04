from __future__ import annotations

import json
import csv
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from typing import Optional, List, Dict, Any

import pandas as pd
import pyautogui
import yaml
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    ElementClickInterceptedException,
    StaleElementReferenceException
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager
from groq import Groq
import PyPDF2

# Setup logging
def setup_logger() -> None:
    if not os.path.exists('./logs'):
        os.makedirs('./logs')
    
    dt = datetime.now().strftime("%m_%d_%y %H_%M_%S ")
    logging.basicConfig(
        filename=f'./logs/{dt}apply_jobs.log',
        format='%(asctime)s::%(name)s::%(levelname)s::%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=logging.INFO
    )
    
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

logger = logging.getLogger(__name__)

class LinkedInBot:
    def __init__(self, config_path: str = "/Users/rupinajay/Developer/Job Scraper/linkedin_job_apply/config.yaml"):
        logger.info("Initializing LinkedIn Bot...")
        self.load_config(config_path)
        self.setup_browser()
        self.groq_client = Groq(api_key=self.config['groq_api_key'])
        self.user_profile = self.create_user_profile()
        logger.info("Bot initialization complete")

    def load_config(self, config_path: str) -> None:
        logger.info(f"Loading configuration from {config_path}")
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
            
        required_fields = ['username', 'password', 'uploads', 'positions', 'locations']
        for field in required_fields:
            if field not in self.config:
                logger.error(f"Missing required field in config: {field}")
                raise ValueError(f"Missing required field in config: {field}")
        logger.info("Configuration loaded successfully")

    def setup_browser(self) -> None:
        logger.info("Setting up Chrome browser...")
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        self.browser = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()),
            options=options
        )
        self.wait = WebDriverWait(self.browser, 30)
        logger.info("Browser setup complete")

    def create_user_profile(self) -> dict:
        logger.info("Creating user profile from uploaded documents...")
        profile = {
            "resume_text": self.extract_text_from_pdf(self.config['uploads']['Resume']),
            "cover_letter_text": self.read_text_file(self.config['uploads']['Cover Letter']),
            "salary_expectation": self.config['salary'],
            "phone_number": self.config.get('phone_number', '')
        }
        logger.info("User profile created successfully")
        return profile

    @staticmethod
    def extract_text_from_pdf(pdf_path: str) -> str:
        logger.info(f"Extracting text from PDF: {pdf_path}")
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text()
            logger.info("PDF text extraction successful")
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
        return text

    @staticmethod
    def read_text_file(file_path: str) -> str:
        logger.info(f"Reading text file: {file_path}")
        try:
            with open(file_path, 'r') as file:
                text = file.read()
            logger.info("Text file read successful")
            return text
        except Exception as e:
            logger.error(f"Error reading text file: {e}")
            return ""
    
    def login(self) -> None:
        """Login to LinkedIn"""
        logger.info("Initiating LinkedIn login process...")
        try:
            # Navigate to LinkedIn login page
            self.browser.get("https://www.linkedin.com/login")
            time.sleep(5)
            
            # Find and fill username
            username_field = self.browser.find_element(By.ID, "username")
            username_field.clear()
            username_field.send_keys(self.config['username'])
            logger.info("Username entered")
            time.sleep(1)
            
            # Find and fill password
            password_field = self.browser.find_element(By.ID, "password")
            password_field.clear()
            password_field.send_keys(self.config['password'])
            logger.info("Password entered")
            time.sleep(1)
            
            # Click sign in button
            sign_in_button = self.browser.find_element(By.CSS_SELECTOR, "button[type='submit']")
            sign_in_button.click()
            logger.info("Sign in button clicked")
            
            # Wait for login to complete
            time.sleep(10)
            
            # Verify login success
            if any(term in self.browser.current_url for term in ["feed", "mynetwork", "jobs"]):
                logger.info("Successfully logged into LinkedIn")
            else:
                # Check for verification
                if "checkpoint" in self.browser.current_url or "security" in self.browser.current_url:
                    logger.warning("Additional verification required. Please complete it manually.")
                    # Wait for manual verification
                    input("Press Enter after completing verification...")
                else:
                    logger.warning("Login might have failed - check if additional verification is needed")
            
            # Wait additional time for page to load completely
            time.sleep(5)
            
        except Exception as e:
            logger.error(f"Error during login process: {str(e)}")
            raise

    def search_jobs(self) -> None:
        """Start the job search process"""
        logger.info("Starting job search process...")
        for position in self.config['positions']:
            for location in self.config['locations']:
                logger.info(f"Searching for {position} in {location}")
                self.search_and_apply(position, location)

    def search_and_apply(self, position: str, location: str) -> None:
        """Search for jobs and apply to them"""
        try:
            position_encoded = quote(position)
            location_encoded = quote(location)
            
            search_url = (
                f"https://www.linkedin.com/jobs/search/?keywords={position_encoded}"
                f"&location={location_encoded}&f_LF=f_AL"
            )
            
            if self.config.get('experience_level'):
                search_url += f"&f_E={','.join(map(str, self.config['experience_level']))}"
            
            logger.info(f"Navigating to search URL: {search_url}")
            self.browser.get(search_url)
            time.sleep(7)
            
            # Scroll to load more jobs
            self.scroll_job_list()
            
            # Find job cards
            job_cards = self.find_job_cards()
            
            if not job_cards:
                logger.warning(f"No jobs found for {position} in {location}")
                return
            
            # Process each job card
            for index, card in enumerate(job_cards[:10]):  # Limit to first 10 jobs
                try:
                    logger.info(f"\n{'='*50}")
                    logger.info(f"Processing job {index + 1} of {len(job_cards)}")
                    
                    # Process the job card
                    self.process_job_card(card)
                    
                    # Add random delay between jobs
                    delay = random.uniform(2, 4)
                    logger.info(f"Waiting {delay:.1f} seconds before next job")
                    time.sleep(delay)
                    
                except Exception as e:
                    logger.error(f"Error processing job card: {str(e)}")
                    continue
                
        except Exception as e:
            logger.error(f"Error in search_and_apply: {str(e)}")

    def scroll_job_list(self) -> None:
        """Scroll through job listings to load more jobs"""
        try:
            for _ in range(3):  # Scroll 3 times
                self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                self.browser.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
        except Exception as e:
            logger.error(f"Error scrolling job list: {str(e)}")

    def find_job_cards(self) -> List[WebElement]:
        """Find job cards using multiple selectors"""
        job_selectors = [
            "div.job-card-container",
            "li.jobs-search-results__list-item",
            "div.jobs-search-results__list-item",
            "div[data-job-id]",
            ".job-card-list__entity-lockup",
            ".jobs-search-results__list-item--active"
        ]
        
        all_cards = []
        for selector in job_selectors:
            try:
                cards = self.browser.find_elements(By.CSS_SELECTOR, selector)
                if cards:
                    all_cards.extend(cards)
                    logger.info(f"Found {len(cards)} jobs using selector: {selector}")
            except Exception:
                continue
        
        # Remove duplicates while preserving order
        seen = set()
        unique_cards = []
        for card in all_cards:
            card_id = card.get_attribute('data-job-id')
            if card_id not in seen:
                seen.add(card_id)
                unique_cards.append(card)
        
        logger.info(f"Found total of {len(unique_cards)} unique job cards")
        return unique_cards

    def find_radio_buttons(self, section: WebElement) -> List[WebElement]:
        """Find all radio buttons in a section"""
        try:
            radio_selectors = [
                "input[type='radio']",
                "[data-test-text-selectable-option__input]",
                ".fb-form-element_checkbox[type='radio']",
                "[role='radio']",
                "input[type='radio'][data-test-text-selectable-option_input]",
                ".jobs-easy-apply-form-element input[type='radio']"
            ]
            
            all_radio_buttons = []
            for selector in radio_selectors:
                try:
                    buttons = section.find_elements(By.CSS_SELECTOR, selector)
                    all_radio_buttons.extend(buttons)
                    if buttons:
                        logger.info(f"Found {len(buttons)} radio buttons using selector: {selector}")
                except Exception as e:
                    continue
            
            return all_radio_buttons
            
        except Exception as e:
            logger.error(f"Error finding radio buttons: {str(e)}")
            return []
    
    def determine_field_type(self, section: WebElement) -> str:
        """Determine the type of input field"""
        try:
            # Get the HTML content of the section for analysis
            html_content = section.get_attribute('outerHTML').lower()
            
            # Check for select/dropdown fields
            if self.is_select_field(section):
                logger.info("Field type determined: select")
                return "select"
            
            # Check for file upload
            if any(term in html_content for term in ["upload", "file", "resume", "cv"]):
                if section.find_elements(By.CSS_SELECTOR, "input[type='file']"):
                    logger.info("Field type determined: file_upload")
                    return "file_upload"
            
            # Check for textarea
            if section.find_elements(By.TAG_NAME, "textarea"):
                logger.info("Field type determined: textarea")
                return "textarea"
            
            # Check for radio buttons
            radio_buttons = section.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            if radio_buttons:
                logger.info("Field type determined: radio")
                return "radio"
            
            # Check for checkboxes
            checkboxes = section.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
            if checkboxes:
                logger.info("Field type determined: checkbox")
                return "checkbox"
            
            # Check for text/number input
            text_inputs = section.find_elements(
                By.CSS_SELECTOR, 
                "input[type='text'], input[type='number'], input[type='email'], input[type='tel']"
            )
            if text_inputs:
                logger.info("Field type determined: text")
                return "text"
            
            # Check for custom input implementations
            custom_input_selectors = [
                ".artdeco-text-input--input",
                ".fb-single-line-text__input",
                ".jobs-easy-apply-form-element__input",
                ".artdeco-text-input--container input"
            ]
            
            for selector in custom_input_selectors:
                if section.find_elements(By.CSS_SELECTOR, selector):
                    logger.info("Field type determined: text (custom implementation)")
                    return "text"
            
            logger.warning("Could not determine field type, defaulting to unknown")
            return "unknown"
            
        except Exception as e:
            logger.error(f"Error determining field type: {str(e)}")
            return "unknown"

    def handle_checkbox(self, field: Dict) -> None:
        """Handle checkbox fields"""
        try:
            question = field["question"].lower()
            section = field["section"]
            
            # Find checkbox element
            checkbox = section.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
            
            # Determine if checkbox should be checked based on question
            should_check = self.should_check_checkbox(question)
            
            # Get current state
            is_checked = checkbox.is_selected()
            
            # Change state if needed
            if should_check and not is_checked:
                self.click_element(checkbox)
                logger.info(f"Checked checkbox for: {question}")
            elif not should_check and is_checked:
                self.click_element(checkbox)
                logger.info(f"Unchecked checkbox for: {question}")
            else:
                logger.info(f"Checkbox already in correct state for: {question}")
                
        except Exception as e:
            logger.error(f"Error handling checkbox: {str(e)}")

    def should_check_checkbox(self, question: str) -> bool:
        """Determine if a checkbox should be checked based on the question"""
        try:
            question = question.lower()
            
            # Always check these types of boxes
            always_check_terms = [
                "agree",
                "accept",
                "consent",
                "confirm",
                "acknowledge",
                "i have read",
                "i understand",
                "privacy policy",
                "terms",
                "conditions"
            ]
            
            # Check if question contains any of the always-check terms
            if any(term in question for term in always_check_terms):
                logger.info(f"Checkbox should be checked based on term match: {question}")
                return True
                
            # For other types of checkboxes, use LLM to decide
            if any(term in question for term in ["follow", "subscribe", "notification", "update"]):
                answer = self.get_llm_answer(f"Should I check this box: {question}? Answer only Yes or No.")
                should_check = answer.lower().strip() == "yes"
                logger.info(f"LLM decided checkbox should be {'checked' if should_check else 'unchecked'}: {question}")
                return should_check
            
            # Default behavior for unknown checkbox types
            logger.info(f"Using default checkbox behavior (checked) for: {question}")
            return True
            
        except Exception as e:
            logger.error(f"Error determining checkbox state: {str(e)}")
            return True  # Default to checking the box in case of error

    def click_element(self, element: WebElement) -> None:
        """Click an element with fallback to JavaScript click"""
        try:
            # Scroll element into view
            self.browser.execute_script("arguments[0].scrollIntoView(true);", element)
            time.sleep(0.5)
            
            # Try regular click
            try:
                element.click()
            except:
                # Try JavaScript click
                self.browser.execute_script("arguments[0].click();", element)
                
            time.sleep(0.5)  # Wait for any animations/changes
            
            logger.info("Successfully clicked element")
                
        except Exception as e:
            logger.error(f"Error clicking element: {str(e)}")

    def handle_form_buttons(self) -> bool:
        """Handle form navigation buttons"""
        try:
            button_selectors = [
                ("Submit application", "submit"),
                ("Review application", "review"),
                ("Next", "next"),
                ("Continue", "continue")
            ]
            
            for button_text, button_type in button_selectors:
                try:
                    buttons = self.browser.find_elements(By.XPATH, 
                        f"//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{button_text.lower()}')]")
                    
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            logger.info(f"Clicking {button_text} button")
                            self.click_element(button)
                            
                            if button_type == "submit":
                                logger.info("Application submitted successfully")
                                return False
                            
                            return True
                            
                except Exception as e:
                    logger.error(f"Error handling {button_text} button: {str(e)}")
                    continue
            
            logger.info("No more buttons found")
            return False
            
        except Exception as e:
            logger.error(f"Error in handle_form_buttons: {str(e)}")
            return False

    def is_select_field(self, section: WebElement) -> bool:
        """Determine if a section contains a select/dropdown field"""
        try:
            # Check for standard select element
            if section.find_elements(By.TAG_NAME, "select"):
                return True
            
            # Check for custom dropdown implementations
            custom_dropdown_selectors = [
                "[role='combobox']",
                "[aria-haspopup='listbox']",
                ".artdeco-dropdown__trigger",
                ".select-choices",
                ".custom-select",
                "[data-control-name='select']",
                ".jobs-easy-apply-form-element__dropdown",
                ".fb-dropdown__select"
            ]
            
            for selector in custom_dropdown_selectors:
                if section.find_elements(By.CSS_SELECTOR, selector):
                    return True
            
            # Check for common dropdown attributes
            html_content = section.get_attribute('outerHTML').lower()
            dropdown_indicators = [
                'dropdown',
                'select',
                'combobox',
                'listbox',
                'chosen-container'
            ]
            
            if any(indicator in html_content for indicator in dropdown_indicators):
                elements = section.find_elements(By.CSS_SELECTOR, "[class*='dropdown'], [class*='select']")
                if elements:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking for select field: {str(e)}")
            return False

    def get_select_options(self, section: WebElement) -> List[str]:
        """Get all options from a dropdown/select element"""
        options = []
        try:
            # Try standard select element first
            select_elements = section.find_elements(By.TAG_NAME, "select")
            if select_elements:
                select = Select(select_elements[0])
                options = [opt.text.strip() for opt in select.options if opt.text.strip()]
                logger.info(f"Found {len(options)} options in standard select")
                return options
            
            # Try custom dropdown implementations
            dropdown_triggers = section.find_elements(By.CSS_SELECTOR, 
                "[role='combobox'], [aria-haspopup='listbox'], .artdeco-dropdown__trigger")
            
            if dropdown_triggers:
                # Click to open dropdown
                self.click_element(dropdown_triggers[0])
                time.sleep(1)
                
                # Try multiple selectors for options
                option_selectors = [
                    "li.artdeco-dropdown__item",
                    "[role='option']",
                    ".artdeco-dropdown__content div",
                    ".select-choices li",
                    ".custom-select-options li",
                    ".jobs-easy-apply-form-element__dropdown-option"
                ]
                
                for selector in option_selectors:
                    option_elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    if option_elements:
                        options = [opt.text.strip() for opt in option_elements if opt.text.strip()]
                        break
                
                # Close dropdown
                self.click_element(dropdown_triggers[0])
                
                logger.info(f"Found {len(options)} options in custom dropdown")
                return options
            
        except Exception as e:
            logger.error(f"Error getting select options: {str(e)}")
        
        return options

    def get_job_details(self, card: WebElement) -> Dict[str, str]:
        """Extract job details from the job card"""
        details = {}
        try:
            # Try multiple selectors for job title
            title_selectors = [
                "h3.job-card-list__title",
                "h3.base-search-card__title",
                ".job-card-container__link",
                ".job-card-list__title",
                "a.job-card-container__link.job-card-list__title",
                ".jobs-unified-top-card__job-title"
            ]
            
            # Try to get job title
            for selector in title_selectors:
                try:
                    title_element = card.find_element(By.CSS_SELECTOR, selector)
                    details['title'] = title_element.text.strip()
                    break
                except:
                    continue
            
            # Try multiple selectors for company name
            company_selectors = [
                "h4.job-card-container__company-name",
                "h4.base-search-card__subtitle",
                ".job-card-container__company-name",
                ".job-card-container__primary-description",
                "a.job-card-container__company-name",
                ".jobs-unified-top-card__company-name"
            ]
            
            # Try to get company name
            for selector in company_selectors:
                try:
                    company_element = card.find_element(By.CSS_SELECTOR, selector)
                    details['company'] = company_element.text.strip()
                    break
                except:
                    continue
            
            # Try to get location
            location_selectors = [
                ".job-card-container__metadata-item",
                ".job-card-container__location",
                ".job-card-container__secondary-description",
                "span.job-card-container__location",
                ".jobs-unified-top-card__bullet"
            ]
            
            for selector in location_selectors:
                try:
                    location_element = card.find_element(By.CSS_SELECTOR, selector)
                    details['location'] = location_element.text.strip()
                    break
                except:
                    continue
            
            # Try to get job ID
            try:
                job_id = card.get_attribute('data-job-id')
                if job_id:
                    details['job_id'] = job_id
            except:
                pass
            
            # Log the details found
            if details:
                logger.info("Job Details:")
                for key, value in details.items():
                    logger.info(f"{key}: {value}")
            else:
                logger.warning("No job details could be extracted")
            
            return details
        
        except Exception as e:
            logger.error(f"Error extracting job details: {str(e)}")
            return {
                'title': '',
                'company': '',
                'location': '',
                'job_id': ''
            }
    
    def process_job_card(self, card: WebElement) -> None:
        """Process a single job card"""
        try:
            # Scroll the job card into view
            self.browser.execute_script("arguments[0].scrollIntoView(true);", card)
            time.sleep(1)
            
            # Get job details
            job_details = self.get_job_details(card)
            
            # Check if job should be skipped based on title
            if self.should_skip_job(job_details.get('title', '')):
                logger.info("Skipping job based on title")
                return
            
            # Click the job card
            self.click_element(card)
            time.sleep(3)
            
            # Check for Easy Apply button
            easy_apply_button = self.find_easy_apply_button()
            if easy_apply_button:
                logger.info("Found Easy Apply button")
                self.click_element(easy_apply_button)
                logger.info("Clicked Easy Apply button")
                
                # Process application form
                self.process_application_form()
            else:
                logger.info("No Easy Apply button found for this job")
            
        except Exception as e:
            logger.error(f"Error processing job card: {str(e)}")

    def find_easy_apply_button(self) -> Optional[WebElement]:
        """Find the Easy Apply button"""
        try:
            button_selectors = [
                "button.jobs-apply-button",
                "button[data-control-name='jobdetails_topcard_inapply']",
                ".jobs-apply-button--top-card",
                ".jobs-apply-button",
                "[aria-label='Easy Apply']",
                ".jobs-unified-top-card__easy-apply-button"
            ]
            
            for selector in button_selectors:
                buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                for button in buttons:
                    if "Easy Apply" in button.text:
                        return button
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding Easy Apply button: {str(e)}")
            return None

    def should_skip_job(self, title: str) -> bool:
        """Check if job should be skipped based on title"""
        if not title:
            return False
            
        title_lower = title.lower()
        blacklist_terms = self.config.get('blackListTitles', [])
        
        return any(term.lower() in title_lower for term in blacklist_terms)

    def process_application_form(self) -> None:
        """Process the application form with better flow control"""
        try:
            max_steps = 20
            current_step = 0
            processed_fields = set()
            
            while current_step < max_steps:
                current_step += 1
                logger.info(f"\nProcessing application step {current_step}")
                time.sleep(2)
                
                # Check for submission confirmation message
                if self.is_application_submitted():
                    logger.info("Application submitted successfully!")
                    return
                
                # Handle file upload if present
                self.handle_file_upload_if_present()
                
                # Analyze form fields
                form_fields = self.analyze_form_fields()
                
                if not form_fields:
                    # If no fields found and no buttons, application might be complete
                    if not self.find_form_buttons():
                        logger.info("No more fields or buttons found - application process completed")
                        return
                
                if form_fields:
                    # Process each unique field
                    for field in form_fields:
                        field_id = f"{field['question']}_{field['type']}"
                        
                        # Skip if already processed
                        if field_id in processed_fields:
                            logger.info(f"Skipping already processed field: {field['question']}")
                            continue
                        
                        # Process the field
                        self.process_field(field)
                        processed_fields.add(field_id)
                        time.sleep(0.5)
                
                # Handle navigation buttons
                button_result = self.handle_form_buttons()
                if not button_result:
                    # No buttons found, check if application is complete
                    if self.is_application_submitted():
                        logger.info("Application submitted successfully!")
                        return
                    break
                
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error in process_application_form: {str(e)}")

    def is_application_submitted(self) -> bool:
        """Check if the application has been submitted successfully"""
        try:
            # Common success message patterns
            success_selectors = [
                "//div[contains(text(), 'application was sent')]",
                "//div[contains(text(), 'successfully submitted')]",
                "//div[contains(text(), 'Application submitted')]",
                ".artdeco-modal__content div:contains('application was sent')",
                ".artdeco-modal__content div:contains('successfully')"
            ]
            
            for selector in success_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.browser.find_elements(By.XPATH, selector)
                    else:
                        elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    
                    if elements and any(elem.is_displayed() for elem in elements):
                        # Try to find and click close button if present
                        self.close_success_modal()
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking application submission: {str(e)}")
            return False

    def close_success_modal(self) -> None:
        """Attempt to close the success message modal"""
        try:
            # Common close button selectors
            close_selectors = [
                "button[aria-label='Dismiss']",
                "button.artdeco-modal__dismiss",
                ".artdeco-modal__dismiss",
                "button.artdeco-button[aria-label='Close']",
                "button[data-test-modal-close-button]"
            ]
            
            for selector in close_selectors:
                try:
                    close_buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    for button in close_buttons:
                        if button.is_displayed():
                            self.click_element(button)
                            logger.info("Closed success modal")
                            return
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"Error closing success modal: {str(e)}")

    def find_form_buttons(self) -> bool:
        """Check if any form navigation buttons are present"""
        try:
            button_selectors = [
                "button[type='submit']",
                "button.artdeco-button--primary",
                ".jobs-apply-button",
                "button:contains('Next')",
                "button:contains('Submit')",
                "button:contains('Review')"
            ]
            
            for selector in button_selectors:
                elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(elem.is_displayed() for elem in elements):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error finding form buttons: {str(e)}")
            return False


    def handle_file_upload_if_present(self) -> None:
        """Handle file upload if present on the form"""
        try:
            file_upload_selectors = [
                "input[type='file']",
                "input[name='file']",
                "input[accept='.pdf,.doc,.docx']"
            ]
            
            for selector in file_upload_selectors:
                upload_elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                for upload_element in upload_elements:
                    try:
                        # Determine if it's resume or cover letter
                        element_html = upload_element.get_attribute('outerHTML').lower()
                        if "resume" in element_html or "cv" in element_html:
                            upload_element.send_keys(self.config['uploads']['Resume'])
                            logger.info("Uploaded resume")
                        elif "cover" in element_html:
                            upload_element.send_keys(self.config['uploads']['Cover Letter'])
                            logger.info("Uploaded cover letter")
                        time.sleep(1)
                    except Exception as e:
                        logger.error(f"Error uploading file: {str(e)}")
                        
        except Exception as e:
            logger.error(f"Error handling file upload: {str(e)}")

    def analyze_form_fields(self) -> List[Dict]:
        """Analyze and return all form fields and their types"""
        form_data = []
        try:
            # Try multiple selectors to find form sections
            selectors = [
                ".jobs-easy-apply-form-section__grouping",
                ".fb-dash-form-element",
                ".artdeco-text-input--container",
                "[data-test-form-element]",
                ".jobs-easy-apply-form-element",
                ".jobs-easy-apply-modal__content",
                ".jobs-easy-apply-form-section",
                ".artdeco-modal__content"
            ]
            
            form_sections = []
            for selector in selectors:
                sections = self.browser.find_elements(By.CSS_SELECTOR, selector)
                if sections:
                    form_sections.extend(sections)
                    logger.info(f"Found {len(sections)} sections using selector: {selector}")
            
            # Remove duplicates while preserving order
            seen = set()
            form_sections = [x for x in form_sections if not (x in seen or seen.add(x))]
            
            for section in form_sections:
                try:
                    # Get question/label text
                    question = self.get_question_text(section)
                    if not question:
                        continue
                    
                    logger.info(f"\nAnalyzing field: {question}")
                    
                    # Create base field data
                    field_data = {
                        "question": question,
                        "section": section,
                        "type": "unknown"
                    }
                    
                    # Determine field type and get additional data
                    field_type = self.determine_field_type(section)
                    field_data["type"] = field_type
                    
                    # Get additional data based on field type
                    if field_type == "select":
                        field_data["options"] = self.get_select_options(section)
                        logger.info(f"Select options: {field_data['options']}")
                    elif field_type == "radio":
                        field_data["options"] = self.get_radio_options(section)
                        logger.info(f"Radio options: {field_data['options']}")
                    elif field_type in ["text", "textarea"]:
                        field_data["element"] = self.get_input_element(section, field_type)
                        if field_data["element"]:
                            field_data["placeholder"] = field_data["element"].get_attribute("placeholder")
                    
                    form_data.append(field_data)
                    logger.info(f"Field type determined: {field_type}")
                    
                except Exception as e:
                    logger.error(f"Error analyzing form section: {str(e)}")
                    continue
            
        except Exception as e:
            logger.error(f"Error in analyze_form_fields: {str(e)}")
        
        return form_data
    
    def process_field(self, field: Dict) -> None:
        """Process a single form field"""
        try:
            question = field["question"]
            field_type = field["type"]
            
            logger.info(f"\nProcessing field: {question} (Type: {field_type})")
            
            if field_type == "select":
                self.handle_select(field)
            elif field_type in ["text", "textarea"]:
                self.handle_text_input(field)
            elif field_type == "radio":
                self.handle_radio_buttons(field)
            elif field_type == "checkbox":
                self.handle_checkbox(field)
            elif field_type == "file_upload":
                self.handle_file_upload(field)
            
            time.sleep(0.5)  # Small delay after processing each field
            
        except Exception as e:
            logger.error(f"Error processing field: {str(e)}")

    def handle_select(self, field: Dict) -> None:
        """Handle dropdown/select fields"""
        try:
            question = field["question"].lower()
            section = field["section"]
            
            # First try standard select element
            select_elements = section.find_elements(By.TAG_NAME, "select")
            if select_elements:
                self.handle_standard_select(select_elements[0], question)
                return
            
            # Try custom dropdown
            dropdown_triggers = section.find_elements(By.CSS_SELECTOR, 
                "[role='combobox'], [aria-haspopup='listbox'], .artdeco-dropdown__trigger")
            
            if dropdown_triggers:
                self.handle_custom_dropdown(dropdown_triggers[0], question)
                return
            
            logger.warning(f"No select element found for: {question}")
            
        except Exception as e:
            logger.error(f"Error handling select field: {str(e)}")

    def handle_standard_select(self, select_element: WebElement, question: str) -> None:
        """Handle standard HTML select element"""
        try:
            select = Select(select_element)
            options = [opt.text.strip() for opt in select.options if opt.text.strip()]
            
            if not options:
                logger.warning("No options found in select element")
                return
            
            # Handle phone country code
            if "country code" in question:
                for option in options:
                    if any(term in option.lower() for term in ["india", "+91"]):
                        select.select_by_visible_text(option)
                        logger.info(f"Selected country code: {option}")
                        return
            
            # Handle years of experience
            elif "experience" in question:
                for option in options:
                    if "1" in option or "one" in option.lower():
                        select.select_by_visible_text(option)
                        logger.info(f"Selected experience: {option}")
                        return
            
            # For other dropdowns, select first non-empty option
            for option in options[1:]:  # Skip first option if it's a placeholder
                if option.strip():
                    select.select_by_visible_text(option)
                    logger.info(f"Selected option: {option}")
                    return
            
            # If no other option found, select first option
            if options[0].strip():
                select.select_by_visible_text(options[0])
                logger.info(f"Selected first option: {options[0]}")
                
        except Exception as e:
            logger.error(f"Error handling standard select: {str(e)}")

    def handle_custom_dropdown(self, trigger_element: WebElement, question: str) -> None:
        """Handle custom dropdown implementation"""
        try:
            # Click to open dropdown
            self.click_element(trigger_element)
            time.sleep(1)
            
            # Find options
            option_selectors = [
                "li.artdeco-dropdown__item",
                "[role='option']",
                ".artdeco-dropdown__content div",
                ".select-choices li",
                ".custom-select-options li"
            ]
            
            options = []
            for selector in option_selectors:
                elements = self.browser.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    options = elements
                    break
            
            if not options:
                logger.warning("No options found in custom dropdown")
                return
            
            # Handle phone country code
            if "country code" in question:
                for option in options:
                    option_text = option.text.strip().lower()
                    if any(term in option_text for term in ["india", "+91"]):
                        self.click_element(option)
                        logger.info(f"Selected country code: {option_text}")
                        return
            
            # Handle years of experience
            elif "experience" in question:
                for option in options:
                    option_text = option.text.strip().lower()
                    if "1" in option_text or "one" in option_text:
                        self.click_element(option)
                        logger.info(f"Selected experience: {option_text}")
                        return
            
            # For other dropdowns, select first valid option
            for option in options[1:]:  # Skip first option if it's a placeholder
                if option.text.strip():
                    self.click_element(option)
                    logger.info(f"Selected option: {option.text}")
                    return
            
            # If no other option found, select first option
            if options[0].text.strip():
                self.click_element(options[0])
                logger.info(f"Selected first option: {options[0].text}")
                
        except Exception as e:
            logger.error(f"Error handling custom dropdown: {str(e)}")

    def get_element_text(self, element: WebElement) -> Optional[str]:
        """Get text from an element using multiple methods"""
        try:
            text = None
            
            # Method 1: Direct text
            text = element.text.strip()
            if text:
                return text
            
            # Method 2: aria-label attribute
            text = element.get_attribute("aria-label")
            if text:
                return text.strip()
            
            # Method 3: value attribute
            text = element.get_attribute("value")
            if text:
                return text.strip()
            
            # Method 4: Check associated label
            try:
                # Check for id and corresponding label
                element_id = element.get_attribute("id")
                if element_id:
                    label = element.find_element(By.CSS_SELECTOR, f"label[for='{element_id}']")
                    if label:
                        return label.text.strip()
            except:
                pass
            
            # Method 5: Check parent label
            try:
                parent_label = element.find_element(By.XPATH, "ancestor::label")
                if parent_label:
                    return parent_label.text.strip()
            except:
                pass
            
            # Method 6: Check following sibling span/div
            try:
                sibling = element.find_element(By.XPATH, "following-sibling::span | following-sibling::div")
                if sibling:
                    return sibling.text.strip()
            except:
                pass
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting element text: {str(e)}")
            return None

    def get_radio_options(self, section: WebElement) -> List[str]:
        """Get all options from radio button group"""
        try:
            options = []
            radio_buttons = self.find_radio_buttons(section)
            
            for button in radio_buttons:
                try:
                    # Try multiple methods to get option text
                    option_text = None
                    
                    # Method 1: Check label element
                    try:
                        label = button.find_element(By.XPATH, "following-sibling::label")
                        option_text = label.text.strip()
                    except:
                        pass
                    
                    # Method 2: Check parent label
                    if not option_text:
                        try:
                            label = button.find_element(By.XPATH, "ancestor::label")
                            option_text = label.text.strip()
                        except:
                            pass
                    
                    # Method 3: Check associated label by id
                    if not option_text:
                        try:
                            button_id = button.get_attribute("id")
                            if button_id:
                                label = self.browser.find_element(By.CSS_SELECTOR, f"label[for='{button_id}']")
                                option_text = label.text.strip()
                        except:
                            pass
                    
                    # Method 4: Check aria-label
                    if not option_text:
                        option_text = button.get_attribute("aria-label")
                    
                    # Method 5: Check value attribute
                    if not option_text:
                        option_text = button.get_attribute("value")
                    
                    if option_text:
                        options.append(option_text)
                        
                except Exception as e:
                    logger.error(f"Error getting radio button text: {str(e)}")
                    continue
            
            logger.info(f"Found {len(options)} radio options: {options}")
            return options
            
        except Exception as e:
            logger.error(f"Error getting radio options: {str(e)}")
            return []
    
    def handle_text_input(self, field: Dict) -> None:
        """Handle text input fields"""
        try:
            question = field["question"].lower()
            element = field["element"]
            
            # Clear existing text
            element.clear()
            
            # Essential fields with dynamic values from config/resume
            essential_fields = {
                'first name': 'Rupin',
                'last name': 'Ajay',
                'phone': '+918248863436',
                'mobile': '+918248863436',
                'email': 'rupinajay@gmail.com',
                'company': 'Zyngate',
                'university': 'Shiv Nadar University Chennai',
                'gpa': '8.2'
            }
            
            # Check if this is an essential field
            for key, value in essential_fields.items():
                if key in question:
                    element.send_keys(value)
                    logger.info(f"Filled essential field {question}: {value}")
                    return

            # Check if the input should be numeric before getting LLM answer
            is_numeric, constraints = self.is_numeric_input(element)
            
            if is_numeric:
                numeric_answer = self.get_numeric_answer(question, constraints)
                if numeric_answer is not None:
                    element.send_keys(numeric_answer)
                    logger.info(f"Filled numeric input for: {question} with value: {numeric_answer}")
                else:
                    # Use fallback value if no valid numeric answer
                    fallback = self.get_fallback_numeric_value(constraints)
                    element.send_keys(str(fallback))
                    logger.info(f"Used fallback numeric value: {fallback} for {question}")
            else:
                # For non-numeric fields, use LLM with rate limiting
                answer = self.get_rate_limited_llm_answer(question)
                element.send_keys(answer)
                logger.info(f"Filled text input for: {question}")
                
        except Exception as e:
            logger.error(f"Error handling text input: {str(e)}")


    def get_radio_options(self, section: WebElement) -> List[str]:
        """Get all options from radio button group"""
        try:
            options = []
            radio_buttons = self.find_radio_buttons(section)
            
            for button in radio_buttons:
                # Try multiple methods to get option text
                option_text = self.get_element_text(button)
                if option_text:
                    options.append(option_text)
            
            logger.info(f"Found {len(options)} radio options")
            return options
            
        except Exception as e:
            logger.error(f"Error getting radio options: {str(e)}")
            return []

    def is_numeric_input(self, element: WebElement) -> tuple[bool, dict]:
        """Dynamically determine if input requires numeric value and its constraints"""
        try:
            constraints = {}
            
            # Check input attributes first
            input_type = element.get_attribute("type")
            if input_type == "number":
                self.extract_input_constraints(element, constraints)
                return True, constraints

            # Get the error message if present (after a failed input attempt)
            error_message = self.get_error_message(element)
            if error_message:
                if any(term in error_message.lower() for term in ["number", "numeric", "digits"]):
                    self.extract_range_from_error(error_message, constraints)
                    return True, constraints

            # Check if question implies numeric answer
            question = self.get_question_text(element.find_element(By.XPATH, ".."))
            if question:
                # Use LLM to determine if the question requires a numeric answer
                is_numeric = self.check_if_numeric_question(question)
                if is_numeric:
                    return True, constraints

            return False, constraints

        except Exception as e:
            logger.error(f"Error in is_numeric_input: {str(e)}")
            return False, {}

    def get_error_message(self, element: WebElement) -> Optional[str]:
        """Get error message associated with an input field"""
        try:
            error_selectors = [
                "..//div[contains(@class, 'error')]",
                "..//div[contains(@class, 'feedback')]",
                "..//span[contains(@class, 'error')]",
                "..//p[contains(@class, 'error')]"
            ]
            
            for selector in error_selectors:
                try:
                    error_element = element.find_element(By.XPATH, selector)
                    if error_element.is_displayed():
                        return error_element.text.strip()
                except:
                    continue
            
            return None
        except Exception as e:
            logger.error(f"Error getting error message: {str(e)}")
            return None

    def check_if_numeric_question(self, question: str) -> bool:
        """Use LLM to determine if question requires numeric answer"""
        try:
            prompt = f"Does this question require a numeric answer (yes/no)? Question: {question}"
            response = self.get_rate_limited_llm_answer(prompt)
            return response.lower().strip() == "yes"
        except Exception as e:
            logger.error(f"Error checking numeric question: {str(e)}")
            return False

    def get_numeric_answer(self, question: str, constraints: dict) -> Optional[str]:
        """Get appropriate numeric answer for the question"""
        try:
            # Ask LLM for appropriate numeric answer
            prompt = (
                f"For the question: '{question}', provide ONLY a number as answer. "
                f"Consider the context and provide a reasonable value. "
                f"If it's about experience, provide a realistic number of years. "
                f"If it's about projects or products, provide a reasonable count. "
                f"Just return the number, nothing else."
            )
            
            answer = self.get_rate_limited_llm_answer(prompt)
            
            # Extract number from answer
            numeric_match = re.search(r'\d+(?:\.\d+)?', answer)
            if numeric_match:
                value = float(numeric_match.group())
                
                # Validate against constraints
                if constraints.get("min") is not None:
                    value = max(value, constraints["min"])
                if constraints.get("max") is not None:
                    value = min(value, constraints["max"])
                
                # Convert to integer if whole number
                if value.is_integer():
                    value = int(value)
                
                return str(value)
            
            return self.get_fallback_numeric_value(constraints)
            
        except Exception as e:
            logger.error(f"Error getting numeric answer: {str(e)}")
            return self.get_fallback_numeric_value(constraints)

    def validate_numeric_value(self, value: float, constraints: dict) -> str:
        """Validate and adjust numeric value to fit constraints"""
        try:
            if constraints.get("min") is not None:
                value = max(float(value), constraints["min"])
            if constraints.get("max") is not None:
                value = min(float(value), constraints["max"])
                
            # Return as integer if whole number, otherwise as float
            return str(int(value) if value.is_integer() else value)
            
        except Exception as e:
            logger.error(f"Error validating numeric value: {str(e)}")
            return str(value)

    def get_fallback_numeric_value(self, constraints: dict) -> str:
        """Get safe fallback value within constraints"""
        try:
            min_val = constraints.get("min", 0)
            max_val = constraints.get("max", 99)
            
            if min_val <= max_val:
                return str(min_val)
            
            return "1"  # Ultimate fallback
            
        except Exception as e:
            logger.error(f"Error getting fallback value: {str(e)}")
            return "1"
        
    def handle_radio_buttons(self, field: Dict) -> None:
        """Handle radio button fields"""
        try:
            question = field["question"].lower()
            options = field.get("options", [])
            
            if not options:
                logger.warning(f"No options found for radio field: {question}")
                return
            
            # Get predefined answer based on question
            answer = self.get_predefined_answer(question)
            if not answer:
                # Use LLM for other questions
                answer = self.get_llm_answer(question)
            
            radio_buttons = field["section"].find_elements(By.CSS_SELECTOR, "input[type='radio']")
            
            # Try to find best matching option
            best_match = None
            for i, option in enumerate(options):
                if answer.lower() in option.lower() or option.lower() in answer.lower():
                    best_match = radio_buttons[i]
                    break
            
            if best_match:
                self.click_element(best_match)
                logger.info(f"Selected radio option: {options[options.index(best_match)]}")
            else:
                # Default to first option if no match found
                self.click_element(radio_buttons[0])
                logger.info(f"Selected first radio option: {options[0]}")
                
        except Exception as e:
            logger.error(f"Error handling radio buttons: {str(e)}")
        
    def get_predefined_answer(self, question: str) -> Optional[str]:
        """Get predefined answer for common questions"""
        question = question.lower()
        
        predefined_answers = {
            'phone': '+91-8248863436',
            'salary': self.config['salary'],
            'experience': '1',
            'name': 'Rupin Ajay',
            'website': 'linkedin.com/rupinajay',
            'github': 'github.com/rupinajay',
            'degree': 'Bachelor of Technology in Computer Science and Engineering',
            'graduate': 'No',
            'start': 'Immediately',
            'relocate': 'No',
            'remote': 'Yes',
            'education': 'B.Tech in Computer Science and Engineering',
            'university': 'Shiv Nadar University Chennai',
            'gpa': '8.2',
            'graduation': 'April 2026'
        }
        
        for key, value in predefined_answers.items():
            if key in question:
                return value
        
        return None

    def get_question_text(self, section: WebElement) -> Optional[str]:
        """Extract question/label text from a form section"""
        try:
            # List of selectors to find question text, in order of preference
            label_selectors = [
                "label",
                ".artdeco-text-input--label",
                ".jobs-easy-apply-form-element__label",
                ".t-16.t-bold",
                ".fb-form-element-label",
                "legend",
                "[for]",
                ".artdeco-text-input--label",
                ".fb-dash-form-element__label",
                "h3",
                ".jobs-easy-apply-modal__section-title"
            ]
            
            # Try each selector until we find text
            for selector in label_selectors:
                try:
                    elements = section.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        text = element.text.strip()
                        if text:
                            logger.info(f"Found question text: {text}")
                            return text
                except Exception:
                    continue

            # Try getting aria-label if no text found
            try:
                aria_label = section.get_attribute("aria-label")
                if aria_label:
                    logger.info(f"Found question from aria-label: {aria_label}")
                    return aria_label
            except Exception:
                pass

            # Try looking for any text content
            try:
                text = section.text.strip()
                if text:
                    lines = text.split('\n')
                    # Take first non-empty line as question
                    for line in lines:
                        if line.strip():
                            logger.info(f"Found question from text content: {line.strip()}")
                            return line.strip()
            except Exception:
                pass

            return None

        except Exception as e:
            logger.error(f"Error getting question text: {str(e)}")
            return None

    def get_input_element(self, section: WebElement, field_type: str) -> Optional[WebElement]:
        """Get the input element from a form section"""
        try:
            if field_type == "textarea":
                return section.find_element(By.TAG_NAME, "textarea")
            elif field_type == "text":
                return section.find_element(By.CSS_SELECTOR, "input[type='text'], input[type='number']")
            return None
        except Exception as e:
            logger.error(f"Error getting input element: {str(e)}")
            return None

    def get_element_label(self, element: WebElement) -> Optional[str]:
        """Get the label text for a form element"""
        try:
            # Try multiple methods to get label text
            
            # 1. Try aria-label
            aria_label = element.get_attribute("aria-label")
            if aria_label:
                return aria_label
            
            # 2. Try associated label by id
            element_id = element.get_attribute("id")
            if element_id:
                try:
                    label_elem = self.browser.find_element(By.CSS_SELECTOR, f"label[for='{element_id}']")
                    if label_elem:
                        return label_elem.text.strip()
                except:
                    pass
            
            # 3. Try parent label
            try:
                parent_label = element.find_element(By.XPATH, "ancestor::label")
                if parent_label:
                    return parent_label.text.strip()
            except:
                pass
            
            # 4. Try sibling label
            try:
                sibling_label = element.find_element(By.XPATH, "../label")
                if sibling_label:
                    return sibling_label.text.strip()
            except:
                pass
            
            # 5. Try getting text from parent div
            try:
                parent_div = element.find_element(By.XPATH, "..")
                if parent_div:
                    return parent_div.text.strip()
            except:
                pass

            return None
            
        except Exception as e:
            logger.error(f"Error getting element label: {str(e)}")
            return None

    def handle_text_input(self, field: Dict) -> None:
        """Handle text input fields"""
        try:
            question = field["question"].lower()
            element = field["element"]
            
            # Clear existing text
            element.clear()
            
            # Essential fields with dynamic values from config/resume
            essential_fields = {
                'first name': 'Rupin',
                'last name': 'Ajay',
                'phone': '+918248863436',
                'mobile': '+918248863436',
                'email': 'rupinajay@gmail.com',
                'company': 'Zyngate',  # Current company
                'university': 'Shiv Nadar University Chennai',
                'gpa': '8.2'
            }
            
            # Check if this is an essential field
            for key, value in essential_fields.items():
                if key in question:
                    element.send_keys(value)
                    logger.info(f"Filled essential field {question}: {value}")
                    return

            # For all other fields, use LLM with rate limiting
            answer = self.get_rate_limited_llm_answer(question)
            element.send_keys(answer)
            logger.info(f"Filled text input for: {question}")
            
        except Exception as e:
            logger.error(f"Error handling text input: {str(e)}")

    def get_rate_limited_llm_answer(self, question: str) -> str:
        """Get LLM answer with rate limiting"""
        max_retries = 3
        base_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** attempt)
                    logger.info(f"Rate limit hit. Waiting {delay} seconds before retry...")
                    time.sleep(delay)
                
                return self.get_llm_answer(question)
                
            except Exception as e:
                if "429" in str(e):  # Rate limit error
                    if attempt == max_retries - 1:
                        logger.error("Rate limit reached, using fallback answer")
                        return self.get_fallback_answer(question)
                    continue
                else:
                    logger.error(f"Error getting LLM answer: {str(e)}")
                    return self.get_fallback_answer(question)
        
        return self.get_fallback_answer(question)

    def get_llm_answer(self, question: str) -> str:
        """Get answer from LLM based on question"""
        try:
            question_lower = question.lower()
            resume_text = self.user_profile['resume_text']
            
            # Adjust prompt based on question type
            if any(term in question_lower for term in ['title', 'position', 'role']):
                prompt = f"""
                Based on my resume, provide only my current job title or the role I'm most qualified for.
                Give a single, brief title (2-4 words maximum).
                
                Resume:
                {resume_text}
                
                Current role at Zyngate as Python AI Developer and relevant experience.
                Answer with just the title:
                """
            else:
                prompt = f"""
                You are me answering a job application question. Provide a direct, first-person response.
                
                My resume:
                {resume_text}

                Question: {question}

                Rules:
                1. Answer in first person
                2. Depending on question, give the response accordingly.
                3. For yes/no: Answer only "Yes" or "No"
                4. For numbers: Provide only the number
                5. For titles/positions: Provide only the title
                6. Always answer "No" to relocation

                Answer:
                """

            response = self.groq_client.chat.completions.create(
                messages=[{
                    "role": "user",
                    "content": prompt
                }],
                model="mixtral-8x7b-32768",
                temperature=0.1,
                max_tokens=50
            )

            answer = response.choices[0].message.content.strip()
            
            # Clean up the response
            answer = re.sub(r'^I would say that |^I can say that |^I would like to say that ', '', answer)
            answer = answer.split('.')[0]  # Take only the first sentence
            
            # For title/position questions, ensure it's super brief
            if any(term in question_lower for term in ['title', 'position', 'role']):
                answer = answer.split('\n')[0].strip()  # Take first line only
                answer = re.sub(r'^I am |^I\'m |^Currently |^Working as ', '', answer)  # Remove common prefixes
            
            logger.info(f"LLM provided answer: {answer}")
            return answer

        except Exception as e:
            logger.error(f"Error getting LLM answer: {str(e)}")
            return self.get_fallback_answer(question)

    def get_fallback_answer(self, question: str) -> str:
        """Provide fallback answers when LLM fails"""
        question = question.lower()
        
        # Only include truly essential fallback answers
        fallback_answers = {
            'phone': '+91-8248863436',
            'email': 'rupinajay@gmail.com',
            'name': 'Rupin Ajay',
            'company': 'Zynggate',
            'university': 'Shiv Nadar University Chennai',
            'gpa': '8.2',
            'graduate': 'No',
            'relocate': 'No'
        }
        
        for key, value in fallback_answers.items():
            if key in question:
                return value
        
        # For title/position questions when LLM fails
        if any(term in question for term in ['title', 'position', 'role']):
            return "Software Engineer"  # Generic fallback title
        
        return 'Yes'  # Default fallback

    def handle_form_buttons(self) -> str:
        """Handle form navigation buttons with improved flow"""
        try:
            # Check buttons in priority order
            button_configs = [
                {
                    "type": "submit",
                    "text": "Submit application",
                    "selectors": [
                        "button[aria-label='Submit application']",
                        "//button[contains(., 'Submit application')]",
                        "button[data-control-name='submit_unify']"
                    ]
                },
                {
                    "type": "review",
                    "text": "Review",  # Changed from "Review application" to just "Review"
                    "selectors": [
                        "button[aria-label='Review']",
                        "//button[contains(., 'Review')]",
                        "button[data-control-name='review']",
                        "//button[text()='Review']"  # Exact text match
                    ]
                },
                {
                    "type": "next",
                    "text": "Next",
                    "selectors": [
                        "button[aria-label='Continue to next step']",
                        "//button[contains(., 'Next')]",
                        "//button[contains(., 'Continue')]"
                    ]
                }
            ]
            
            for button_config in button_configs:
                for selector in button_config["selectors"]:
                    try:
                        if selector.startswith("//"):
                            buttons = self.browser.find_elements(By.XPATH, selector)
                        else:
                            buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                        
                        for button in buttons:
                            if button.is_displayed() and button.is_enabled():
                                button_text = button.text.strip()
                                logger.info(f"Found button with text: '{button_text}'")
                                
                                # For Review button, check exact text match
                                if button_config["type"] == "review" and button_text != "Review":
                                    continue
                                
                                # Scroll button into view
                                self.browser.execute_script("arguments[0].scrollIntoView(true);", button)
                                time.sleep(1)
                                
                                # Click the button
                                try:
                                    button.click()
                                except:
                                    self.browser.execute_script("arguments[0].click();", button)
                                
                                logger.info(f"Clicked {button_config['text']} button")
                                
                                if button_config["type"] == "submit":
                                    time.sleep(3)  # Wait longer for submission
                                    return "submitted"
                                elif button_config["type"] == "review":
                                    time.sleep(2)
                                    return "review"
                                else:
                                    time.sleep(1)
                                    return "next"
                                
                    except Exception as e:
                        continue
            
            return "no_buttons"
            
        except Exception as e:
            logger.error(f"Error handling form buttons: {str(e)}")
            return "error"


    def click_element(self, element: WebElement) -> bool:
        """Click an element with fallback to JavaScript click"""
        try:
            # Scroll element into view
            self.browser.execute_script("arguments[0].scrollIntoView(true);", element)
            time.sleep(0.5)
            
            # Try regular click
            try:
                element.click()
            except:
                # Try JavaScript click
                self.browser.execute_script("arguments[0].click();", element)
            
            time.sleep(0.5)
            return True
                
        except Exception as e:
            logger.error(f"Error clicking element: {str(e)}")
            return False
    
    def handle_form_buttons(self) -> str:
        """Handle form navigation buttons and return status"""
        try:
            # First check for submission confirmation
            completion_indicators = [
                "application has been submitted",
                "successfully submitted",
                "thank you for applying",
                "application received"
            ]
            
            page_text = self.browser.page_source.lower()
            if any(indicator in page_text for indicator in completion_indicators):
                logger.info("Application already submitted successfully")
                return "submitted"
            
            # Button hierarchy in order of priority
            button_types = [
                {
                    "text": "Submit application",
                    "type": "submit",
                    "selectors": [
                        "button[aria-label='Submit application']",
                        "button[data-control-name='submit_unify']",
                        "//button[contains(., 'Submit application')]",
                        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')]"
                    ]
                },
                {
                    "text": "Review application",
                    "type": "review",
                    "selectors": [
                        "button[aria-label='Review application']",
                        "button[data-control-name='review_unify']",
                        "//button[contains(., 'Review application')]",
                        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'review')]"
                    ]
                },
                {
                    "text": "Next",
                    "type": "next",
                    "selectors": [
                        "button[aria-label='Continue to next step']",
                        "button[data-control-name='continue_unify']",
                        "//button[contains(., 'Next')]",
                        "//button[contains(., 'Continue')]"
                    ]
                }
            ]
            
            # Look for and click appropriate button
            for button_type in button_types:
                for selector in button_type["selectors"]:
                    try:
                        # Find buttons using either XPath or CSS selector
                        if selector.startswith("//"):
                            buttons = self.browser.find_elements(By.XPATH, selector)
                        else:
                            buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                        
                        for button in buttons:
                            if button.is_displayed() and button.is_enabled():
                                logger.info(f"Found {button_type['text']} button")
                                
                                # Scroll button into view
                                self.browser.execute_script("arguments[0].scrollIntoView(true);", button)
                                time.sleep(1)
                                
                                # Click the button
                                try:
                                    button.click()
                                except:
                                    self.browser.execute_script("arguments[0].click();", button)
                                
                                logger.info(f"Clicked {button_type['text']} button")
                                
                                if button_type["type"] == "submit":
                                    logger.info("Waiting for submission to complete...")
                                    time.sleep(3)
                                    return "submitted"
                                elif button_type["type"] == "review":
                                    logger.info("Clicked Review button, looking for Submit button...")
                                    time.sleep(2)
                                    # After clicking Review, immediately look for Submit button
                                    submit_result = self.click_submit_after_review()
                                    if submit_result:
                                        return "submitted"
                                    return "continue"
                                else:
                                    time.sleep(1)
                                    return "continue"
                                
                    except Exception as e:
                        logger.error(f"Error with button selector {selector}: {str(e)}")
                        continue
            
            logger.info("No more buttons found")
            return "completed"
            
        except Exception as e:
            logger.error(f"Error handling form buttons: {str(e)}")
            return "error"


    def click_submit_after_review(self) -> bool:
        """Look for and click Submit button after clicking Review"""
        try:
            # Wait a bit for the submit button to appear
            time.sleep(2)
            
            # Submit button selectors
            submit_selectors = [
                "button[aria-label='Submit application']",
                "button[data-control-name='submit_unify']",
                "//button[contains(., 'Submit application')]",
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'submit')]"
            ]
            
            for selector in submit_selectors:
                try:
                    if selector.startswith("//"):
                        buttons = self.browser.find_elements(By.XPATH, selector)
                    else:
                        buttons = self.browser.find_elements(By.CSS_SELECTOR, selector)
                    
                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            logger.info("Found Submit button after review")
                            
                            # Scroll button into view
                            self.browser.execute_script("arguments[0].scrollIntoView(true);", button)
                            time.sleep(1)
                            
                            # Click the submit button
                            try:
                                button.click()
                            except:
                                self.browser.execute_script("arguments[0].click();", button)
                            
                            logger.info("Clicked Submit button after review")
                            time.sleep(3)  # Wait for submission to complete
                            return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"Error clicking submit after review: {str(e)}")
            return False
    
    def run(self) -> None:
        """Main method to run the bot"""
        try:
            logger.info("Starting LinkedIn Easy Apply Bot")
            self.login()
            time.sleep(5)
            logger.info("Beginning job search and application process")
            self.search_jobs()
            logger.info("Job application process completed")
        except Exception as e:
            logger.error(f"Error in main run method: {str(e)}")
        finally:
            logger.info("Closing browser")
            self.browser.quit()

if __name__ == "__main__":
    setup_logger()
    logger.info("Initializing LinkedIn Easy Apply Bot")
    bot = LinkedInBot()
    bot.run()