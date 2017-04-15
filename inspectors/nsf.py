#!/usr/bin/env python

import datetime
import logging
import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from utils import utils, inspector

# https://www.nsf.gov/oig/
archive = 1989

# options:
#   standard since/year options for a year range to fetch from.
#
# Notes for IG's web team:

AUDIT_REPORTS_URL = "https://www.nsf.gov/oig/reports/reviews.jsp"
SEMIANNUAL_REPORTS_URL = "https://www.nsf.gov/oig/reports/semiannual.jsp"
TESTIMONY_REPORTS_URL = "https://www.nsf.gov/oig/testimony.jsp"

CASE_REPORTS_URL = "https://www.nsf.gov/oig/case-closeout/results.jsp"
CASE_REPORTS_DATA = {
  'sortAll': 'cn',
  'sballfrm': 'Search',
}

REPORT_PUBLISHED_MAP = {
  "HSN_Summary": datetime.datetime(2013, 9, 30),  # Estimated
}

REPORT_LINK_TEXT = re.compile("Entire.+Document", re.DOTALL)
REPORT_LEADIN_TEXT = re.compile("Available\s+Formats:")


def run(options):
  year_range = inspector.year_range(options, archive)

  # Pull the audit reports
  doc = utils.beautifulsoup_from_url(AUDIT_REPORTS_URL)
  results = doc.select("#inner-content tr")
  if not results:
    raise inspector.NoReportsFoundError("National Science Foundation (audit reports)")
  for result in results:
    # ignore divider lines
    if result.select("img"):
      continue

    report = report_from(result, report_type='audit', year_range=year_range, base_url=AUDIT_REPORTS_URL)
    if report:
      inspector.save_report(report)

  # Pull the semiannual reports
  doc = utils.beautifulsoup_from_url(SEMIANNUAL_REPORTS_URL)
  results = doc.select("#inner-content li")
  if not results:
    raise inspector.NoReportsFoundError("National Science Foundation (semiannual reports)")
  for result in results:
    if not result.text.strip():
      continue
    report = semiannual_report_from(result, year_range)
    if report:
      inspector.save_report(report)

  # Pull the case reports
  response = utils.scraper.post(
    url=CASE_REPORTS_URL,
    data=CASE_REPORTS_DATA,
  )
  doc = BeautifulSoup(response.content, "lxml")
  results = doc.select("#inner-content tr")
  if not results:
    raise inspector.NoReportsFoundError("National Science Foundation (case reports)")
  for index, result in enumerate(results):
    if not index or not result.text.strip():  # Skip the header row and empty rows
      continue
    report = case_report_from(result, CASE_REPORTS_URL, year_range)
    if report:
      inspector.save_report(report)

  # Pull the testimony
  doc = utils.beautifulsoup_from_url(TESTIMONY_REPORTS_URL)
  results = doc.select("#inner-content tr")
  if not results:
    raise inspector.NoReportsFoundError("National Science Foundation (testimony)")
  for result in results:
    if not result.text.strip():
      continue
    report = report_from(result, report_type='testimony', year_range=year_range, base_url=TESTIMONY_REPORTS_URL)
    if report:
      inspector.save_report(report)


def report_from(result, report_type, year_range, base_url):
  link = result.find("a")

  if not link:
    logging.debug("Markup error, skipping: %s" % result)
    return None

  report_url = urljoin(base_url, link['href'])
  report_filename = report_url.split("/")[-1]
  report_id, _ = os.path.splitext(report_filename)

  title = " ".join(link.parent.text.split())

  try:
    last_column_node = result.select("td")[-1]
  except IndexError:
    last_column_node = result.select("td.tabletext")[-1]

  if last_column_node.text.strip():
    published_on_text, *report_id_text = last_column_node.stripped_strings
    if report_id_text:
      # If an explicit report_id is listed, use that.
      report_id = report_id_text[0]
    published_on_text = published_on_text.replace(" ,", ",").strip()
    published_on_text = published_on_text.replace("Februray", "February")
    published_on = datetime.datetime.strptime(published_on_text, '%B %d, %Y')
  else:
    # No text in the last column. This is an incomplete row
    published_on = REPORT_PUBLISHED_MAP[report_id]

  if published_on.year not in year_range:
    logging.debug("[%s] Skipping, not in requested range." % report_url)
    return

  report = {
    'inspector': "nsf",
    'inspector_url': "https://www.nsf.gov/oig/",
    'agency': "nsf",
    'agency_name': "National Science Foundation",
    'type': report_type,
    'report_id': report_id,
    'url': report_url,
    'title': title,
    'published_on': datetime.datetime.strftime(published_on, "%Y-%m-%d"),
  }
  return report


def case_report_from(result, landing_url, year_range):
  link = result.find("a")

  report_url = urljoin(CASE_REPORTS_URL, link['href'])
  report_id = link.text
  title = result.contents[5].text.strip()

  # catch all until this can be more easily diagnosed
  if not title:
    title = "(Untitled)"

  published_on_text = result.contents[3].text
  published_on = datetime.datetime.strptime(published_on_text, '%m/%d/%y')

  if published_on.year not in year_range:
    logging.debug("[%s] Skipping, not in requested range." % report_url)
    return

  report = {
    'inspector': "nsf",
    'inspector_url': "https://www.nsf.gov/oig/",
    'agency': "nsf",
    'agency_name': "National Science Foundation",
    'type': 'inspection',
    'report_id': report_id,
    'url': report_url,
    'title': title,
    'published_on': datetime.datetime.strftime(published_on, "%Y-%m-%d"),
  }
  return report


def semiannual_report_from(result, year_range):
  link = result.find("a")
  report_url = urljoin(SEMIANNUAL_REPORTS_URL, link['href'])

  if not report_url.endswith((".pdf", ".txt")):
    landing_url = report_url

    # Since this page redirects sometimes, we need to see where it redirects
    # to so that we can resolve the relative urls later.
    landing_page_response = utils.scraper.get(landing_url)
    landing_url = landing_page_response.url

    landing_page = BeautifulSoup(landing_page_response.content, "lxml")
    report_leadin_text = landing_page.find(text=REPORT_LEADIN_TEXT)
    report_link_text = landing_page.find(text=REPORT_LINK_TEXT)
    report_link = None
    if report_leadin_text:
      report_link = report_leadin_text.parent.find('a', text='PDF')
      if not report_link:
        report_link = report_leadin_text.parent.find('a', text='TXT')
    elif report_link_text:
      report_link = report_link_text.parent
    if report_link is None:
      raise Exception("No report link found on %s" % landing_url)

    if report_link.get('href'):
      relative_report_url = report_link['href']
    elif report_link.findChild("a"):
      relative_report_url = report_link.findChild("a")['href']
    elif report_link.findParent("a"):
      relative_report_url = report_link.findParent("a")['href']
    report_url = urljoin(landing_url, relative_report_url)

  report_filename = report_url.split("/")[-1]
  report_id, _ = os.path.splitext(report_filename)

  title = "Semiannual Report - {}".format(link.text)

  published_on_text = link.text.strip()
  published_on = datetime.datetime.strptime(published_on_text, '%B %Y')

  if published_on.year not in year_range:
    logging.debug("[%s] Skipping, not in requested range." % report_url)
    return

  report = {
    'inspector': "nsf",
    'inspector_url': "https://www.nsf.gov/oig/",
    'agency': "nsf",
    'agency_name': "National Science Foundation",
    'type': 'semiannual_report',
    'report_id': report_id,
    'url': report_url,
    'title': title,
    'published_on': datetime.datetime.strftime(published_on, "%Y-%m-%d"),
  }
  return report

utils.run(run) if (__name__ == "__main__") else None
