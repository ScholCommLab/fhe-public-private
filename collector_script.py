
# coding: utf-8
import datetime, time
import json
import urllib.parse
import pandas as pd
import configparser

from ATB.ATB.Altmetric import Altmetric
from ATB.ATB.Facebook import Facebook
from ATB.ATB.DBConnection import DBConnection
from ATB.ATB.Utils import resolve_doi, print_progress_bar

# Load config
Config = configparser.ConfigParser()
Config.read('config.cnf')

FACEBOOK_APP_ID = Config.get('facebook', 'app_id')
FACEBOOK_APP_SECRET = Config.get('facebook', 'app_secret')
ALTMETRIC_KEY = Config.get('altmetric', 'key')

# Setup db connection
db_path = 'data/main.db'
db_table = "state_oa"
db_col_names = ['doi','url','resolve_error',
                'og_obj','am_response','timestamp']
db_col_types = ['TEXT', 'TEXT', 'INTEGER',
                'TEXT', 'INTEGER', 'INTEGER',
                'INTEGER', 'INTEGER', 'INTEGER',
                'TEXT', 'TEXT']
unique_col = "doi"

db_con = DBConnection(db_path=db_path,
                      db_table=db_table,
                      db_col_names=db_col_names,
                      db_col_types=db_col_types,
                      unique_col=unique_col)

# Setup APIs
fb_graph = Facebook(FACEBOOK_APP_ID, FACEBOOK_APP_SECRET)
altmetric = Altmetric(api_key = ALTMETRIC_KEY)

# Load DOIs
df = pd.read_csv("data/state_of_oa.csv", encoding = 'utf8')
dois = df.doi

def parse_response(doi, url, timestamp, fb_response, altmetric_response, fb_error = None, altmetric_error = None):
    row = {'doi':str(doi),
           'url':str(url),
           'am_response':json.dumps(altmetric_response),
           'timestamp':str(timestamp)
          }

    return row

i_max = len(dois)
for i, doi in enumerate(dois, 1):
    now = datetime.datetime.now()

    # already handles errors internally (in a terrible way...)
    url = resolve_doi(doi)

    try:
        fb_response = fb_graph.get_object(id=urllib.parse.quote_plus(url),
                                          fields="engagement, og_object")
    except:
        fb_response = {}

    try:
        am_response = altmetric.doi(doi=doi, fetch=True)
    except:
        am_response = None

    row = parse_response(doi, url, now, fb_response, am_response)
    db_con.save_row(row)

    new = datetime.datetime.now()
    delta = new - now
    m, s = divmod(i_max-i, 60)
    h, m = divmod(m, 60)

    # enforce 1 call/sec
    if delta.seconds < 1:
        time.sleep(1- delta.total_seconds())

    print_progress_bar(i, i_max, length=80, suffix="ETA {:d}:{:d}:{:d}".format(h, m, s))
