from intake.source import base
import json
from elasticsearch import Elasticsearch
import pandas as pd

__version__ = '0.0.1'


class Plugin(base.Plugin):
    def __init__(self):
        super(Plugin, self).__init__(name='elasticsearch_table',
                                     version=__version__,
                                     container='dataframe',
                                     partition_access=False)

    def open(self, query, **kwargs):
        """
        Parameters:
            query : str
                Query string (lucene syntax or JSON text)
            qargs: dict
                Set of modifiers to apply to the query
                (http://elasticsearch-py.readthedocs.io/en/master/api.html#elasticsearch)
            kwargs (dict):
                Additional parameters to pass to ElasticSearch init.
        """
        base_kwargs, source_kwargs = self.separate_base_kwargs(kwargs)
        qargs = source_kwargs.pop('qargs', {})
        return ElasticSearchSource(query=query, qargs=qargs,
                                   es_kwargs=source_kwargs,
                                   metadata=base_kwargs['metadata'])


class ElasticSearchSource(base.DataSource):
    """
    Data source which executes arbitrary queries on ElasticSearch

    This is the tabular reader: will return dataframes. Nested return items
    will become dict-like objects in the output.

    Parameters
    ----------
    query: str
       Query to execute. Can either be in Lucene single-line format, or a
       JSON structured query (presented as text)
    qargs: dict
        Further parameters to pass to the query, such as set of indexes to
        consider, filtering, ordering. See
        http://elasticsearch-py.readthedocs.io/en/master/api.html#elasticsearch.Elasticsearch.search
    es_kwargs: dict
        Settings for the ES connection, e.g., a simple local connection may be
        ``{'host': 'localhost', 'port': 9200}``.
    metadata: dict
        Extra information for this source.
    """

    def __init__(self, query, qargs, es_kwargs, metadata):
        self._query = query
        self._qargs = qargs
        self._es_kwargs = es_kwargs
        self._dataframe = None
        self.es = Elasticsearch([es_kwargs])  # maybe should be (more) global?

        super(ElasticSearchSource, self).__init__(container='dataframe',
                                                  metadata=metadata)

    def _run_query(self, size=10):
        try:
            print('JSON', self._qargs)
            q = json.loads(self._query)
            if 'query' not in q:
                print('rationalise')
                q = {'query': q}
            s = self.es.search(body=q, size=size, **self._qargs)
        except (json.JSONDecodeError, TypeError):
            print('lucene')
            s = self.es.search(q=self._query, size=size, **self._qargs)
        return s

    def _get_schema(self):
        """Get schema from first 10 hits"""
        results = self._run_query()
        df = pd.DataFrame([r['_source'] for r in results['hits']['hits']])
        results.pop('hits')
        return base.Schema(datashape=None,
                           dtype=df[:0],
                           shape=(None, df.shape[0]),
                           npartitions=1,
                           extra_metadata=results)

    def _get_partition(self, _):
        """Downloads all data

        ES has a hard maximum of 10000 items to fetch. Otherwise need to
        implement paging, known to ES as "scroll"
        https://stackoverflow.com/questions/41655913/elk-how-do-i-retrieve-more-than-10000-results-events-in-elastic-search
        """
        if self._dataframe is None:
            results = self._run_query(10000)
            df = pd.DataFrame([r['_source'] for r in results['hits']['hits']])
            self._dataframe = df
            results.pop('hits')
            self.shape = df.shape
        return self._dataframe

    def _close(self):
        self._dataframe = None
