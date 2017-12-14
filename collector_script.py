
# coding: utf-8
import datetime, time, sys
import json
import urllib.parse
import pandas as pd
import argparse, configparser
from random import shuffle

from ATB.ATB.Altmetric import Altmetric, AltmetricHTTPException
from ATB.ATB.Facebook import Facebook
from ATB.ATB.DBConnection import DBConnection
from ATB.ATB.Utils import resolve_doi, print_progress_bar

def load_dois(input_filename):
    df = pd.read_csv(input_filename, encoding = 'utf8')
    return list(df.doi)

def load_config():
    # Load config
    Config = configparser.ConfigParser()
    Config.read('config.cnf')
    auth = {
        'fb_app_id': Config.get('facebook', 'app_id'),
        'fb_app_secret': Config.get('facebook', 'app_secret'),
        'altmetric_key': Config.get('altmetric', 'key')
    }
    return auth

def connect_to_db(db_path, db_table):
    db_col_names = ['doi', 'timestamp', 'doi_resolve_status',
                    'doi_resolve_error', 'doi_url', 'fb_og_object',
                    'fb_engagement', 'fb_response_error', 'am_response','am_response_error']
    db_col_types = ['TEXT', 'TEXT', 'INTEGER',
                    'TEXT', 'TEXT', 'TEXT',
                    'TEXT', 'TEXT', 'TEXT', 'TEXT']
    unique_col = "doi"

    db_con = DBConnection(db_path=db_path,
                        db_table=db_table,
                        db_col_names=db_col_names,
                        db_col_types=db_col_types,
                        unique_col=unique_col)
    return db_con

def parse_response(doi, now, doi_resolve_status, doi_resolve_error, doi_url,
                   fb_og_object, fb_engagement, fb_response_error, am_response, am_response_error):
    row = {'doi':str(doi),
           'timestamp':str(now),
           'doi_resolve_status':str(doi_resolve_status),
           'doi_resolve_error':str(doi_resolve_error),
           'doi_url':str(doi_url),
           'fb_og_object':json.dumps(fb_og_object),
           'fb_engagement':json.dumps(fb_engagement),
           'fb_response_error':str(fb_response_error),
           'am_response':json.dumps(am_response),
           'am_response_error':str(am_response_error),
          }

    return row

def fetch_dois(con, dois):
    i_max = len(dois)
    shuffle(dois)
    for i, doi in enumerate(dois, 1):
        now = datetime.datetime.now()

        # Init row values
        doi_resolve_status = None
        doi_resolve_error = None
        doi_url = None
        fb_og_object = None
        fb_engagement = None
        fb_response_error = None
        am_response = None
        am_response_error = None

        # Resolve DOI
        response_status, response = resolve_doi(doi)

        # if the DOI resolving fails (timeouts, too many redirects, ...)
        if response_status == "NoResponse":
            doi_resolve_error = response

        # successfully resolved DOI
        elif response_status == 200:
            doi_resolve_status = response_status
            doi_url = response

            # retriev FB Open Graph Object + engagement
            try:
                fb_response = fb_graph.get_object(id=urllib.parse.quote_plus(doi_url), fields="engagement, og_object")
            except:
                fb_response_error = sys.exc_info()[0]

            try:
                fb_og_object = fb_response['og_object']
                fb_engagement = fb_response['engagement']
            except:
                fb_response_error = "no_og_object"

        # resolved DOI but status_code != 200
        else:
            doi_resolve_status = response_status
            doi_resolve_error = response

        # Get Altmetric Data based on DOI
        try:
            am_response = altmetric.doi(doi=doi, fetch=True)
        except AltmetricHTTPException as e:
            pass
            am_response_error = e


        # Create DB entry
        row = parse_response(doi, now, doi_resolve_status,
                            doi_resolve_error, doi_url, fb_og_object,
                            fb_engagement, fb_response_error, am_response,am_response_error)
        con.save_row(row)

        # Do some nice API things
        new = datetime.datetime.now()
        delta = new - now
        m, s = divmod(i_max-i, 60)
        h, m = divmod(m, 60)

        if delta.seconds < 1:
            time.sleep(1- delta.total_seconds())

        # Print progress bar
        print_progress_bar(i, i_max, length=80, suffix="ETA {:d}:{:d}:{:d}".format(h, m, s))

def fetch_missing_dois(con, dois):
    pass

def fetch_timedout_dois(con, dois):
    pass


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-file", required=True, help="Input file (CSV) containg a list of DOIs")
    ap.add_argument("--db-path", required=True, help="Path to database to be created or used")
    ap.add_argument("--table-name", required=True, help="Specify name of the table to be created or to be used")
    ap.add_argument("--missing-dois", required=False, help="Fetch missing DOIs", action="store_true")
    ap.add_argument("--get-timeouts", required=False, help="Fetch DOIs that timed out & update rows", action="store_true")

    args = vars(ap.parse_args())

    db_path = args['db_path']
    db_table = args['table_name']
    input_filename = args['input_file']

    # Initialise connections and APIs
    dois = load_dois(input_filename)
    auth = load_config()
    con = connect_to_db(db_path, db_table)

    fb_graph = Facebook(app_id=auth['fb_app_id'], app_secret=auth['fb_app_secret'])
    altmetric = Altmetric(api_key=auth['altmetric_key'])

    if args['missing_dois']:
        fetch_missing_dois(con, dois)

    if args['get_timeouts']:
        # this will go back and fill in individual errors. The batch simply doesn't return errors
        fetch_timedout_dois(con, dois)

    else:
        fetch_dois(con, dois)

