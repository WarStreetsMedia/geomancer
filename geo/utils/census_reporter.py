import scrapelib
from urllib import urlencode
import json
import os
from geo.app_config import CACHE_DIR
from string import punctuation
import re

SUMLEV_NAMES = {
    "010": {"name": "nation", "plural": ""},
    "020": {"name": "region", "plural": "regions"},
    "030": {"name": "division", "plural": "divisions"},
    "040": {"name": "state", "plural": "states", "tiger_table": "state"},
    "050": {"name": "county", "plural": "counties", "tiger_table": "county"},
    "060": {"name": "county subdivision", "plural": "county subdivisions", "tiger_table": "cousub"},
    "101": {"name": "block", "plural": "blocks", "tiger_table": "tabblock"},
    "140": {"name": "census tract", "plural": "census tracts", "tiger_table": "tract"},
    "150": {"name": "block group", "plural": "block groups", "tiger_table": "bg"},
    "160": {"name": "place", "plural": "places", "tiger_table": "place"},
    "170": {"name": "consolidated city", "plural": "consolidated cities", "tiger_table": "concity"},
    "230": {"name": "Alaska native regional corporation", "plural": "Alaska native regional corporations", "tiger_table": "anrc"},
    "250": {"name": "native area", "plural": "native areas", "tiger_table": "aiannh"},
    "251": {"name": "tribal subdivision", "plural": "tribal subdivisions", "tiger_table": "aits"},
    "256": {"name": "tribal census tract", "plural": "tribal census tracts", "tiger_table": "ttract"},
    "300": {"name": "MSA", "plural": "MSAs", "tiger_table": "metdiv"},
    "310": {"name": "CBSA", "plural": "CBSAs", "tiger_table": "cbsa"},
    "314": {"name": "metropolitan division", "plural": "metropolitan divisions", "tiger_table": "metdiv"},
    "330": {"name": "CSA", "plural": "CSAs", "tiger_table": "csa"},
    "335": {"name": "combined NECTA", "plural": "combined NECTAs", "tiger_table": "cnecta"},
    "350": {"name": "NECTA", "plural": "NECTAs", "tiger_table": "necta"},
    "364": {"name": "NECTA division", "plural": "NECTA divisions", "tiger_table": "nectadiv"},
    "400": {"name": "urban area", "plural": "urban areas", "tiger_table": "uac"},
    "500": {"name": "congressional district", "plural": "congressional districts", "tiger_table": "cd"},
    "610": {"name": "state senate district", "plural": "state senate districts", "tiger_table": "sldu"},
    "620": {"name": "state house district", "plural": "state house districts", "tiger_table": "sldl"},
    "795": {"name": "PUMA", "plural": "PUMAs", "tiger_table": "puma"},
    "850": {"name": "ZCTA3", "plural": "ZCTA3s"},
    "860": {"name": "ZCTA5", "plural": "ZCTA5s", "tiger_table": "zcta5"},
    "950": {"name": "elementary school district", "plural": "elementary school districts", "tiger_table": "elsd"},
    "960": {"name": "secondary school district", "plural": "secondary school districts", "tiger_table": "scsd"},
    "970": {"name": "unified school district", "plural": "unified school districts", "tiger_table": "unsd"},
}

class CensusReporterError(Exception):
    def __init__(self, message):
        Exception.__init__(self, message)
        self.message = message

class CensusReporter(scrapelib.Scraper):
    """ 
    Subclassing scrapelib here mainly to take advantage of pluggable caching backend.
    """
    
    def __init__(self,
                 raise_errors=True,
                 requests_per_minute=0,
                 retry_attempts=5,
                 retry_wait_seconds=1,
                 header_func=None, 
                 cache_dir=CACHE_DIR):
        self.base_url = 'http://api.censusreporter.org/1.0'
        
        super(CensusReporter, self).__init__(raise_errors=raise_errors,
                                             requests_per_minute=requests_per_minute,
                                             retry_attempts=retry_attempts,
                                             retry_wait_seconds=retry_wait_seconds,
                                             header_func=header_func)
        
        # We might want to talk about configuring an S3 backed cache for this
        # so we don't run the risk of running out of disk space. 
        self.cache_storage = scrapelib.cache.FileCache(cache_dir)
        self.cache_write_only = False

    def geo_search(self, search_term, sumlevs=None):
        """ 
        Search for geoids based upon name of geography
        'sumlevs' is an optional comma seperated string with ACS Summary levels
        """
        regex = re.compile('[%s]' % re.escape(punctuation))
        search_term = regex.sub('', search_term)
        q_dict = {'q': search_term}
        if sumlevs:
            q_dict['sumlevs'] = ','.join(sumlevs)
        params = urlencode(q_dict)
        try:
            response = self.urlopen('%s/geo/search?%s' % (self.base_url, params))
        except scrapelib.HTTPError, e:
            raise CensusReporterError('Census Reporter API returned %s' % e.body)
        results = json.loads(response)
        return results

    def data_show(self, acs='latest', table_ids=None, geo_ids=None, show_detail=False):
        """ 
        Fetch data from given ACS release based upon the table_ids and geo_ids
        Census Reporter only has acs2012_1yr, acs2012_3yr, acs2012_5yr releases
        'table_ids' is a list of tables to fetch
        'geo_ids' is a list of geo_ids to fetch the data for
        'show_detail' is a boolean which, when False will just include the table 
            demoinator column. When True, it means the results will include all
            data in a demormalized form from the given table

        Response should look like:
        {
            'header': [
                'Sex by Educational Attainment for the Population 25 Years and Over, 5th and 6th grade',
                'Sex by Educational Attainment for the Population 25 Years and Over, 7th and 8th grade'
                '...etc...'
            ],
            '04000US55': [
                1427.0,
                723.0,
                3246.0,
                760.0,
                ...etc...,
            ],
            '04000US56': [
                1567.0,
                743.0,
                4453.0,
                657.0,
                ...etc...,
            ]
        }

        The keys are CensusReporter 'geo_ids' and the value is a list that you
        should be able to call the python 'zip' function on with the 'header' key.
        """

        query = {
            'table_ids': ','.join(table_ids),
            'geo_ids': ','.join(geo_ids),
        }
        params = urlencode(query)
        try:
            response = self.urlopen('%s/data/show/%s?%s' % (self.base_url, acs, params))
        except scrapelib.HTTPError, e:
            raise CensusReporterError('Census Reporter API returned %s' % e.body)
        raw_results = json.loads(response)
        results = {'header': []}
        for geo_id in geo_ids:
            results[geo_id] = []
            for table_id in table_ids:
                table_info = raw_results['tables'][table_id]
                title = table_info['title']
                detail_ids = table_info['columns'].keys()
                denominator = table_info['denominator_column_id']
                for detail_id in detail_ids:
                    title = table_info['title']
                    if denominator:
                        detail_title = table_info['columns'][detail_id]['name']
                        title = '%s, %s' % (title, detail_title,)
                    if title not in results['header']:
                        results['header'].extend([title, '%s (error margin)' % title])
                    detail_info = raw_results['data'][geo_id][table_id]
                    results[geo_id].extend([
                        detail_info['estimate'][detail_id], 
                        detail_info['error'][detail_id],
                    ])
        return results