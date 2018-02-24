
# coding: utf-8

# # PKP crawler
# 
# Collect altmetric data for PKP publications
# 
# 1. Collect FB shares from Altmetric.com via DOI
# 2. Collect FB shares from FB directly via URLs
#     - Resolved DOI
#     - Original PKP URL
#     - (opt) PMID
#     - (opt) PMCID

# In[ ]:


import datetime
import time
import sys
import re
import requests
import json
import urllib
from dateutil.parser import parse
from random import shuffle

import pandas as pd
import numpy as np
import lxml.etree as ET
from pathlib import Path
import configparser
from ATB.ATB.Facebook import Facebook
from ATB.ATB.Altmetric import Altmetric

from tqdm import tqdm, tqdm_notebook
tqdm_notebook().pandas()


# In[ ]:


# Load config
Config = configparser.ConfigParser()
Config.read('config.cnf')
FACEBOOK_APP_ID = Config.get('facebook', 'app_id')
FACEBOOK_APP_SECRET = Config.get('facebook', 'app_secret')
ALTMETRIC_KEY = Config.get('altmetric', 'key')

fb_graph = Facebook(app_id=FACEBOOK_APP_ID, app_secret=FACEBOOK_APP_SECRET)
altmetric = Altmetric(api_key = ALTMETRIC_KEY)


# In[ ]:


data_folder = Path("output_files/PKP_rerun/")
input_file = Path("input_files/PKP_20171220.csv")
url_types = ['pkp', 'doi', 'pmc', 'pmid']


# In[ ]:


## Functions
def load_dataset(ids_file, resolv_dois_file):
    ncbi = pd.read_csv(ids_file, parse_dates=['ncbi_ts'], index_col="doi")
    resolved_dois = pd.read_csv(resolv_dois_file, parse_dates=['doi_resolve_ts'], index_col="doi")
    
    df = ncbi.merge(resolved_dois[['doi_url']], left_index=True, right_index=True, how="inner")
    return df.drop_duplicates()

# Facebook
def fb_query(url):
    og_object = None
    og_engagement = None
    og_error = None
    
    try:
        fb_response = fb_graph.get_object(
            id=urllib.parse.quote_plus(url),
            fields="engagement, og_object"
        )
        
        if 'og_object' in fb_response:
            og_object = fb_response['og_object']
        if 'engagement' in fb_response:
            og_engagement = fb_response['engagement']
    except Exception as e:
        og_error = e
  
    return (og_object, og_engagement, og_error)

def collect_fb_engagement(df):
    out_df = df.copy()
    for col in  ['og_obj', 'og_eng', 'og_err', 'ts']:
        out_df[col] = None
    
    rows = list(df.itertuples())
    for row in tqdm(rows, total=len(rows)):
        now = datetime.datetime.now()
        og_object, og_engagement, og_error = fb_query(row.url)
        
        if og_object:
            out_df.loc[(out_df.doi==row.doi) & (out_df.type==row.type), 'og_obj'] = json.dumps(og_object)
        if og_engagement:
            out_df.loc[(out_df.doi==row.doi) & (out_df.type==row.type), 'og_eng'] = json.dumps(og_engagement)
        if og_error:
            out_df.loc[(out_df.doi==row.doi) & (out_df.type==row.type), 'og_err'] = str(og_error)
        out_df.loc[(out_df.doi==row.doi) & (out_df.type==row.type), 'ts'] = str(now)
        
    return out_df
        
# Altmetric
def collect_am_engagement(df):
    result_cols = ['am_resp', 'am_err', 'ts']
    out_df = pd.DataFrame(columns=result_cols, index=df.index)
    
    now = datetime.datetime.now()
    
    rows = list(df.itertuples())
    for row in tqdm(rows, total=len(rows)):
        try:
            am_resp = altmetric.doi(doi=row.Index, fetch=True)
            am_err = None
        except Exception as e:
            am_resp = None
            am_err = e

        out_df.loc[row.Index, 'am_resp'] = json.dumps(am_resp)
        out_df.loc[row.Index, 'am_err'] = str(am_err)
        out_df.loc[row.Index, 'ts'] = str(now)
        
    return out_df

def extract_fb_shares(df):
    result_cols = [x + "_shares" for x in url_types] + [x + "_ogid" for x in url_types]
    shares = pd.DataFrame(columns=result_cols, index=df.doi.unique())
    shares.index.name = "doi"
    
    rows = list(df[df.og_obj.notnull()].itertuples())
    for row in tqdm(rows, total=len(rows)):
        if row.type == "pkp_url":
            shares.loc[row.doi, "pkp_ogid"] = str(json.loads(row.og_obj)['id'])
            shares.loc[row.doi, "pkp_shares"] = float(json.loads(row.og_eng)['share_count'])
        elif row.type == "doi_url":
            shares.loc[row.doi, "doi_ogid"] = str(json.loads(row.og_obj)['id'])
            shares.loc[row.doi, "doi_shares"] = float(json.loads(row.og_eng)['share_count'])        
        elif row.type == "pmid_url":
            shares.loc[row.doi, "pmid_ogid"] = str(json.loads(row.og_obj)['id'])
            shares.loc[row.doi, "pmid_shares"] = float(json.loads(row.og_eng)['share_count'])     
        elif row.type == "pmc_url":
            shares.loc[row.doi, "pmc_ogid"] = str(json.loads(row.og_obj)['id'])
            shares.loc[row.doi, "pmc_shares"] = float(json.loads(row.og_eng)['share_count'])
    return shares

def extract_am_shares(df):
    result_cols = ['am_shares', 'am_id']
    shares = pd.DataFrame(columns=result_cols, index=df.doi.unique())
    shares.index.name = "doi"
    
    rows = list(df[df.am_resp.notnull()].itertuples())
    for row in tqdm(rows, total=len(rows)):
        if pd.notnull(row.am_resp):
            try:
                shares.loc[row.doi, "am_id"] = str(json.loads(row.am_resp)['altmetric_id'])
            except:
                shares.loc[row.doi, "am_id"] = None
            try:
                shares.loc[row.doi, "am_shares"] =  float(json.loads(row.am_resp)['counts']['facebook']['posts_count'])
            except:
                shares.loc[row.doi, "am_shares"] = 0.0
        #if pd.notnull(row.og_eng):
        #    shares.loc[row.doi, row.type.split("_")[0]] =  int(json.loads(row.og_eng)['share_count'])
        
    return shares

def remove_duplicate_og_ids(df):
    """
    Some URLs have been assigned to the same Facebook OG IDs
    Those share numbers should be investigated in more detail
    but for now they are simply being overwritten with NaNs
    """
    
    ids = [x + "_ogid" for x in url_types]

    for _ in ids:
        bad_ones = df[(~df[_].isnull() & df.duplicated(subset=[_], keep=False))].index
        df.loc[bad_ones, _.split("_")[0]] = np.nan
        print("Duplicate {} IDs: {}".format(_, len(bad_ones)))
    return df

def get_identical_doi_pkp_urls(df):
    """
    Sum of the individual FB shares (doi, pkp, pmc, pmid) but taking
    into account that some URLs are identical for resolved DOI and
    original PKP ones.

    DOI == PKP: sum(pkp, pmc, pmid)
    DOI != PKP: sum(pkp, doi, pmc, pmid)
    """
    x = df[df.type.isin(['pkp_url', 'doi_url'])][['url', 'doi']].copy()
    x['netloc'] = x.url.apply(lambda x: urllib.parse.urlparse(x).netloc)
    x['path'] = x.url.apply(lambda x: urllib.parse.urlparse(x).path)
    return x[x[['netloc', 'path']].duplicated()].doi


# In[ ]:


article_with_urls = pd.read_csv(data_folder / "articles_with_urls.csv", index_col="doi")

df_urls = article_with_urls.reset_index().melt(
    value_vars=['pmc_url', 'pmid_url', 'pkp_url', 'doi_url'],
    id_vars='doi',
    value_name="url",
    var_name="type")

df_urls = df_urls.replace(["None", "null", ""], np.nan).dropna()
df_urls = df_urls.drop_duplicates()


# ## Filter out invalid records
# 
# - Different DOIs with identical PKP URLs
# - DOIs resolved to the same URL

# In[ ]:


for _ in [x + "_url" for x in url_types]:
    selection = df_urls.copy()
    selection = selection[selection.type == _]
    selection['netloc'] = selection.url.apply(lambda x: urllib.parse.urlparse(x).netloc)
    selection['path'] = selection.url.apply(lambda x: urllib.parse.urlparse(x).path)
    bad_ones = selection[selection[['netloc', 'path']].duplicated(keep=False)].index
    df_urls = df_urls.drop(bad_ones)
    print("Removed {} rows with bad {}".format(len(bad_ones), _))
    
# Sanity check: duplicate URLs need to appear in both PKP and DOI
df_urls[df_urls.url.isin(df_urls[df_urls.url.duplicated()].url)].type.value_counts()


# ## Collect FB engagement

# In[ ]:


fb_results = collect_fb_engagement(df_urls)
fb_results.to_csv(data_folder / "fb_responses.csv")


# ## Collect Altmetric engagement

# In[ ]:


am_results = collect_am_engagement(article_with_urls)
am_results = am_results.replace("null", np.nan)
am_results.to_csv(data_folder / "am_responses.csv")


# ## Extract Shares

# In[ ]:


# fb_results = pd.read_csv(data_folder / "fb_responses.csv")
# am_results = pd.read_csv(data_folder / "am_responses.csv")


# In[ ]:


fb_extracted = extract_fb_shares(fb_results)


# In[ ]:


am_extracted = extract_am_shares(am_results)


# In[ ]:


fb_extracted = remove_duplicate_og_ids(fb_extracted)
doi_pkp_identical = get_identical_doi_pkp_urls(fb_results)


# In[ ]:


fb_shares = fb_extracted[[x + "_shares" for x in url_types]].astype(float)
am_shares = am_extracted[['am_shares']].astype(float)

fb_shares['fb_shares'] = fb_shares[[x + "_shares" for x in url_types]].sum(axis=1)
fb_shares.loc[doi_pkp_identical, 'fb_shares'] = fb_shares.loc[doi_pkp_identical, ['pkp_shares', 'pmc_shares', 'pmid_shares']].sum(axis=1)


# In[ ]:


fb_shares.to_csv(data_folder / "fb_shares.csv")
am_shares.to_csv(data_folder / "am_shares.csv")

