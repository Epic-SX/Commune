from .asyncio_utils import *
from .dict_utils import *
from .function_utils import *
from .metric_utils import *
from .network_utils import *
from .os_utils import *
from .pandas_utils import *
from .pickle_utils import *
from .time_utils import *
from .torch_utils import *

from typing import *
import os
import time
from time import gmtime, strftime
import random
from copy import deepcopy
import numpy as np
import torch
from importlib import import_module
import pickle
import math
import datetime

class SimpleNamespace:
  def __init__(self, **kwargs):
    self.__dict__.update(kwargs)

class RecursiveNamespace:
  def __init__(self, **kwargs):
    self.__dict__.update(kwargs)
    for k, v in kwargs.items():
        if isinstance(v, dict):
            self.__dict__[k] = RecursiveNamespace(**v)

def check_kwargs(kwargs:dict, defaults:Union[list, dict], return_bool=False):
    '''
    params:
        kwargs: dictionary of key word arguments
        defaults: list or dictionary of keywords->types
    '''
    try:
        assert isinstance(kwargs, dict)
        if isinstance(defaults, list):
            for k in defaults:
                assert k in defaults
        elif isinstance(defaults, dict):
            for k,k_type in defaults.items():
                assert isinstance(kwargs[k], k_type)
    except Exception as e:
        if return_bool:
            return False
        
        else:
            raise e


def cache(path='/tmp/cache.pkl', mode='memory'):

    def cache_fn(fn):
        def wrapped_fn(*args, **kwargs):
            cache_object = None
            self = args[0]

            
            if mode in ['local', 'local.json']:
                try:
                    cache_object = self.client.local.get_pickle(path, handle_error=False)
                except FileNotFoundError as e:
                    pass
            elif mode in ['memory', 'main.memory']:
                if not hasattr(self, '_cache'):
                    self._cache = {}
                else:
                    assert isinstance(self._cache, dict)
                cache_object = self._cache.get(path)
            force_update = kwargs.get('force_update', False)
            if not isinstance(cache_object,type(None)) or force_update:
                return cache_object
    
            cache_object = fn(*args, **kwargs)

            # write
            if mode in ['local']:

                st.write(cache_object)
                self.client.local.put_pickle(data=cache_object,path= path)
            elif mode in ['memory', 'main.memory']:
                '''
                supports main memory caching within self._cache
                '''
                self._cache[path] = cache_object
            return cache_object
        return wrapped_fn
    return cache_fn
    

def merge_objects(self, self2, functions:list):
    self.fn_signature_map = {}
    for fn_key in functions:
        def fn( *args, **kwargs):
            self2_fn = getattr(self2, fn_key)
            return self2_fn(*args, **kwargs)
        setattr(self, fn_key, partial(fn, self))



def round_sig(x, sig=6, small_value=1.0e-9):
    """
    Rounds x to the number of {sig} digits
    :param x:
    :param sig: signifant digit
    :param small_value: smallest possible value
    :return:
    """
    return round(x, sig - int(math.floor(math.log10(max(abs(x), abs(small_value))))) - 1)




def ensure_dir(file_path):
    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory)


def seed_everything(seed: int) -> None:
    "seeding function for reproducibility"
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True


chunk_list = lambda my_list, n: [my_list[i * n:(i + 1) * n] for i in range((len(my_list) + n - 1) // n)]


"""

Methods for Getting Abstractions
=--

"""

def get_module(path,prefix = 'commune'):
    '''
    gets the object
    {module_path}.{object_name}
    ie.
    {model.block.nn.rnn}.{LSTM}
    '''
    assert isinstance(prefix, str)

    if prefix != path[:len(prefix)]:
        path = '.'.join([prefix, path])

    module_path = '.'.join(path.split('.'))

    try:
        module = import_module(module_path)
    except (ModuleNotFoundError) as e:
        if handle_failure :
            return None
        else:
            raise e 

    return module

get_module_file = get_module



def import_object(key):
    module_path = '.'.join(key.split('.')[:-1])
    module = import_module(module_path)
    object_name = key.split('.')[-1]
    obj = getattr(module, object_name)
    return obj



def get_object(path,prefix = 'commune'):
    '''
    gets the object
    {module_path}.{object_name}
    ie.
    {model.block.nn.rnn}.{LSTM}
    '''
    assert isinstance(prefix, str)

    if prefix != path[:len(prefix)]:
        path = '.'.join([prefix, path])

    object_name = path.split('.')[-1]

    try:
        module_class = import_object(path)
    except Exception as e:
        old_path = deepcopy(path)
        path = '.'.join(path.split('.')[:-1] + ['module', path.split('.')[-1]])
        print(f'Trying {path} instead of {old_path}')
        module_class = import_object(path)

    return module_class



def list2str(input):
    assert isinstance(input, list)
    return '.'.join(list(map(str, input)))


def string_replace(cfg, old_str, new_str):

    '''

    :param cfg: dictionary (from yaml)
    :param old_str: old string
    :param new_str: new string replacing old string
    :return:
        cfg after old string is replaced with new string
    '''
    if type(cfg) == dict:
        for k,v in cfg.items():
            if type(v) == str:
                # replace string if list
                if old_str in v:
                    cfg[k] = v.replace(old_str, new_str)
            elif type(v) in [list, dict]:
                # recurse if list or dict
                cfg[k] = string_replace(cfg=v,
                                         old_str=old_str,
                                         new_str=new_str)
            else:
                # for all other types in yaml files
                cfg[k] = v
    elif type(cfg) == list:
        for k, v in enumerate(cfg):
            if type(v) == str:
                # replace string if list
                if old_str in v:
                    cfg[k] = v.replace(old_str, new_str)
            elif type(v) in [list, dict]:
                # recurse if list or dict
                cfg[k] = string_replace(cfg=v,
                                         old_str=old_str,
                                         new_str=new_str)
            else:
                # for all other types in yaml files
                cfg[k] = v

    return cfg


def chunk(sequence,
          chunk_size=None,
          append_remainder=False,
          distribute_remainder=True,
          num_chunks= None):
    # Chunks of 1000 documents at a time.

    if chunk_size is None:
        assert (type(num_chunks) == int)
        chunk_size = len(sequence) // num_chunks

    if chunk_size >= len(sequence):
        return [sequence]
    remainder_chunk_len = len(sequence) % chunk_size
    remainder_chunk = sequence[:remainder_chunk_len]
    sequence = sequence[remainder_chunk_len:]
    sequence_chunks = [sequence[j:j + chunk_size] for j in range(0, len(sequence), chunk_size)]

    if append_remainder:
        # append the remainder to the sequence
        sequence_chunks.append(remainder_chunk)
    else:
        if distribute_remainder:
            # distributes teh remainder round robin to each of the chunks
            for i, remainder_val in enumerate(remainder_chunk):
                chunk_idx = i % len(sequence_chunks)
                sequence_chunks[chunk_idx].append(remainder_val)

    return sequence_chunks


def even_number_split(number=10, splits=2):
    starting_bin_value = number // splits
    split_bins = splits * [starting_bin_value]
    left_over_number = number % starting_bin_value
    for i in range(splits):
        split_bins[i] += 1
        left_over_number -= 1
        if left_over_number == 0:
            break
    return split_bins




