from __future__ import annotations

import math
import time
import random
import regex as re
from typing import Optional
from datetime import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from urllib.parse import urlparse, urlunparse, unquote
import json
import logging
from pathlib import Path
import matplotlib.pyplot as plt
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
headers = {
    "authority": "www.linkedin.com",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# Enums for job types and search filters
class JobType(Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"

class ExperienceLevel(Enum):
    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    ASSOCIATE = "associate"
    MID_SENIOR = "mid_senior"
    DIRECTOR = "director"
    EXECUTIVE = "executive"

@dataclass
class Location:
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    
    def __str__(self):
        parts = []
        if self.city:
            parts.append(self.city)
        if self.state:
            parts.append(self.state)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

@dataclass
class JobPost:
    id: str
    title: str
    company_name: str
    location: Location
    date_posted: Optional[datetime]
    job_url: str
    salary_info: Optional[str] = None
    description: Optional[str] = None
    job_type: Optional[list[JobType]] = None
    job_level: Optional[str] = None
    company_industry: Optional[str] = None
    company_url: Optional[str] = None
    job_function: Optional[str] = None
    scraped_date: datetime = datetime.now()

class LinkedInScraper:
    def __init__(self, search_term: str, location: Optional[str] = None, 
                 distance: Optional[int] = None, experience_level: Optional[ExperienceLevel] = None):
        self.base_url = "https://www.linkedin.com"
        self.search_term = search_term
        self.location = location
        self.distance = distance
        self.experience_level = experience_level
        self.session = requests.Session()
        self.session.headers.update(headers)
        self.jobs_data = []

    def scrape_jobs(self, num_jobs: int = 100) -> list[JobPost]:
        """
        Main method to scrape LinkedIn jobs
        """
        logger.info(f"Starting to scrape {num_jobs} jobs for '{self.search_term}'")
        start = 0
        
        while len(self.jobs_data) < num_jobs:
            try:
                params = self._build_search_params(start)
                response = self._make_request(params)
                
                if not response:
                    break
                
                job_cards = self._parse_job_cards(response)
                
                if not job_cards:
                    break
                
                for job_card in job_cards:
                    if len(self.jobs_data) >= num_jobs:
                        break
                        
                    job_data = self._extract_job_data(job_card)
                    if job_data:
                        self.jobs_data.append(job_data)
                        
                start += len(job_cards)
                self._apply_delay()
                
            except Exception as e:
                logger.error(f"Error during scraping: {str(e)}")
                break
                
        logger.info(f"Successfully scraped {len(self.jobs_data)} jobs")
        return self.jobs_data

    def _build_search_params(self, start: int) -> dict:
        """
        Build search parameters for LinkedIn API request
        """
        params = {
            "keywords": self.search_term,
            "location": self.location,
            "distance": self.distance,
            "start": start,
        }
        
        if self.experience_level:
            params["f_E"] = self.experience_level.value
            
        return {k: v for k, v in params.items() if v is not None}

    def _make_request(self, params: dict) -> Optional[requests.Response]:
        """
        Make HTTP request to LinkedIn
        """
        try:
            response = self.session.get(
                f"{self.base_url}/jobs-guest/jobs/api/seeMoreJobPostings/search",
                params=params,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Error: Status code {response.status_code}")
                return None
                
            return response
            
        except Exception as e:
            logger.error(f"Request error: {str(e)}")
            return None

    def _parse_job_cards(self, response: requests.Response) -> list[Tag]:
        """
        Parse job cards from response HTML
        """
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.find_all("div", class_="base-search-card")

    def _extract_job_data(self, job_card: Tag) -> Optional[JobPost]:
        """
        Extract data from a single job card
        """
        try:
            # Extract basic job information
            title = self._extract_text(job_card, "span", "sr-only")
            company = self._extract_text(job_card, "h4", "base-search-card__subtitle")
            location_text = self._extract_text(job_card, "span", "job-search-card__location")
            
            # Extract job URL and ID
            href_tag = job_card.find("a", class_="base-card__full-link")
            job_url = href_tag.get('href', '').split('?')[0] if href_tag else None
            job_id = job_url.split('-')[-1] if job_url else None
            
            # Parse location
            location = self._parse_location(location_text)
            
            # Extract posting date
            date_posted = self._extract_date(job_card)
            
            # Extract salary information
            salary_info = self._extract_text(job_card, "span", "job-search-card__salary-info")
            
            # Create job post object
            job_post = JobPost(
                id=f"li-{job_id}" if job_id else None,
                title=title,
                company_name=company,
                location=location,
                date_posted=date_posted,
                job_url=job_url,
                salary_info=salary_info
            )
            
            # Get detailed information if available
            detailed_info = self.get_job_details(job_url) if job_url else None
            if detailed_info:
                for key, value in detailed_info.items():
                    setattr(job_post, key, value)
            
            return job_post
            
        except Exception as e:
            logger.error(f"Error extracting job data: {str(e)}")
            return None
        
    def _extract_text(self, element: Tag, tag: str, class_: str) -> Optional[str]:
        """
        Helper method to extract text from HTML elements
        """
        found_element = element.find(tag, class_=class_)
        return found_element.get_text(strip=True) if found_element else None

    def _extract_date(self, job_card: Tag) -> Optional[datetime]:
        """
        Extract and parse posting date
        """
        date_tag = job_card.find("time", class_="job-search-card__listdate")
        if date_tag and "datetime" in date_tag.attrs:
            try:
                return datetime.strptime(date_tag["datetime"], "%Y-%m-%d")
            except:
                return None
        return None

    def _parse_location(self, location_string: str) -> Location:
        """
        Parse location string into Location object
        """
        if not location_string:
            return Location()
            
        parts = location_string.split(', ')
        
        if len(parts) == 2:
            return Location(city=parts[0], state=parts[1])
        elif len(parts) == 3:
            return Location(city=parts[0], state=parts[1], country=parts[2])
        else:
            return Location(city=location_string)

    def _apply_delay(self):
        """
        Apply random delay between requests
        """
        time.sleep(random.uniform(2, 4))

    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert job data to pandas DataFrame
        """
        # Create a list to store formatted job data
        formatted_jobs = []
        
        for job in self.jobs_data:
            job_dict = {
                'Job ID': job.id,
                'Title': job.title,
                'Company': job.company_name,
                'Location': str(job.location),
                'Location City': job.location.city,
                'Location State': job.location.state,
                'Location Country': job.location.country,
                'Date Posted': job.date_posted,
                'Job URL': job.job_url,
                'Salary Info': job.salary_info,
                'Description': job.description,
                'Job Type': str(job.job_type) if job.job_type else None,
                'Job Level': job.job_level,
                'Industry': job.company_industry,
                'Company URL': job.company_url,
                'Job Function': job.job_function,
                'Scraped Date': job.scraped_date
            }
            formatted_jobs.append(job_dict)
        
        df = pd.DataFrame(formatted_jobs)
        if 'Job ID' in df.columns:
            df.set_index('Job ID', inplace=True)
        
        return df

    def save_results(self, output_dir: str = "linkedin_jobs_output"):
        """
        Save results in multiple formats
        """
        # Create output directory if it doesn't exist
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Generate timestamp for filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"linkedin_jobs_{timestamp}"
        
        # Convert to DataFrame
        df = self.to_dataframe()
        
        # Save as CSV
        csv_path = Path(output_dir) / f"{base_filename}.csv"
        df.to_csv(csv_path, encoding='utf-8-sig')
        logger.info(f"Saved CSV to {csv_path}")
        
        # Save as Excel
        excel_path = Path(output_dir) / f"{base_filename}.xlsx"
        df.to_excel(excel_path, engine='openpyxl')
        logger.info(f"Saved Excel to {excel_path}")
        
        # Save as JSON
        json_path = Path(output_dir) / f"{base_filename}.json"
        df.to_json(json_path, orient='records', lines=True, force_ascii=False, indent=2)
        logger.info(f"Saved JSON to {json_path}")
        
        # Create visualizations
        self._create_visualizations(df, output_dir, base_filename)

    def _create_visualizations(self, df: pd.DataFrame, output_dir: str, base_filename: str):
        """
        Create and save visualizations
        """
        try:
            # Company distribution
            plt.figure(figsize=(12, 6))
            df['Company'].value_counts().head(10).plot(kind='bar')
            plt.title('Top 10 Companies Hiring')
            plt.xlabel('Company')
            plt.ylabel('Number of Jobs')
            plt.tight_layout()
            plt.savefig(Path(output_dir) / f"{base_filename}_companies.png")
            plt.close()
            
            # Location distribution
            plt.figure(figsize=(12, 6))
            df['Location City'].value_counts().head(10).plot(kind='bar')
            plt.title('Top 10 Job Locations')
            plt.xlabel('City')
            plt.ylabel('Number of Jobs')
            plt.tight_layout()
            plt.savefig(Path(output_dir) / f"{base_filename}_locations.png")
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating visualizations: {str(e)}")

    def get_job_details(self, job_url: str) -> Optional[dict]:
        """
        Get detailed job information from job page
        """
        if not job_url:
            return None
            
        try:
            logger.info(f"Fetching detailed information for job: {job_url}")
            
            response = self.session.get(job_url, timeout=10)
            if response.status_code != 200:
                logger.error(f"Failed to get job details. Status code: {response.status_code}")
                return None
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Extract job description
            description_div = soup.find(
                "div", 
                class_=lambda x: x and "show-more-less-html__markup" in x
            )
            description = description_div.get_text(strip=True) if description_div else None
            
            # Extract job type
            job_type = self._extract_job_type(soup)
            
            # Extract job level
            job_level = self._extract_job_level(soup)
            
            # Extract company industry
            company_industry = self._extract_company_industry(soup)
            
            # Extract company URL
            company_url = self._extract_company_url(soup)
            
            # Extract job function
            job_function = self._extract_job_function(soup)
            
            return {
                "description": description,
                "job_type": job_type,
                "job_level": job_level,
                "company_industry": company_industry,
                "company_url": company_url,
                "job_function": job_function
            }
            
        except Exception as e:
            logger.error(f"Error getting job details: {str(e)}")
            return None

    def _extract_job_type(self, soup: BeautifulSoup) -> Optional[list[JobType]]:
        """
        Extract job type from job page
        """
        try:
            job_type_h3 = soup.find(
                "h3", 
                string=lambda x: x and "Employment type" in x
            )
            if job_type_h3:
                job_type_span = job_type_h3.find_next_sibling(
                    "span", 
                    class_="description__job-criteria-text"
                )
                if job_type_span:
                    job_type_text = job_type_span.get_text(strip=True).lower()
                    return [JobType(job_type_text)] if job_type_text in [e.value for e in JobType] else None
        except Exception as e:
            logger.error(f"Error extracting job type: {str(e)}")
        return None

    def _extract_job_level(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract job level from job page
        """
        try:
            level_h3 = soup.find(
                "h3", 
                string=lambda x: x and "Seniority level" in x
            )
            if level_h3:
                level_span = level_h3.find_next_sibling(
                    "span", 
                    class_="description__job-criteria-text"
                )
                return level_span.get_text(strip=True) if level_span else None
        except Exception as e:
            logger.error(f"Error extracting job level: {str(e)}")
        return None

    def _extract_company_industry(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract company industry from job page
        """
        try:
            industry_h3 = soup.find(
                "h3", 
                string=lambda x: x and "Industries" in x
            )
            if industry_h3:
                industry_span = industry_h3.find_next_sibling(
                    "span", 
                    class_="description__job-criteria-text"
                )
                return industry_span.get_text(strip=True) if industry_span else None
        except Exception as e:
            logger.error(f"Error extracting company industry: {str(e)}")
        return None

    def _extract_company_url(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract company URL from job page
        """
        try:
            company_link = soup.find(
                "a", 
                class_=lambda x: x and "company-link" in x
            )
            return company_link.get('href') if company_link else None
        except Exception as e:
            logger.error(f"Error extracting company URL: {str(e)}")
        return None

    def _extract_job_function(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract job function from job page
        """
        try:
            function_h3 = soup.find(
                "h3", 
                string=lambda x: x and "Job function" in x
            )
            if function_h3:
                function_span = function_h3.find_next_sibling(
                    "span", 
                    class_="description__job-criteria-text"
                )
                return function_span.get_text(strip=True) if function_span else None
        except Exception as e:
            logger.error(f"Error extracting job function: {str(e)}")
        return None

def main():
    # Example usage
    scraper = LinkedInScraper(
        search_term="AI Intern",
        location="India",
        distance=100,
        experience_level=ExperienceLevel.ENTRY_LEVEL
    )
    
    # Scrape jobs
    scraper.scrape_jobs()
    
    # Save results
    scraper.save_results()
    
    # Display some basic statistics
    df = scraper.to_dataframe()
    print("\n=== Job Search Results ===")
    print(f"Total Jobs Found: {len(df)}")
    print("\nTop Companies:")
    print(df['Company'].value_counts().head())
    print("\nTop Locations:")
    print(df['Location City'].value_counts().head())

if __name__ == "__main__":
    main()