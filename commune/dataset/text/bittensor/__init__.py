""" Create and init the GenesisTextDataset class, which handles dataloading from ipfs
"""

# The MIT License (MIT)
# Copyright © 2021 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import argparse
import os
import copy
from typing import Optional
import bittensor
from . import dataset_impl

logger = dataset_impl.logger
class dataset:
    """ Factory class for the GenesisTextDataset class or the mocked GenesisTextDataset
    The GenesisTextDataset downloads text data from the bittensor mountain dataset. 
    The class makes http requests to bittensor's IPFS backend server which contains the full dataset.
    By default, the GenesisTextDataset class will return a fully functioning pytorch dataloader.

    Examples:: 
            >>> dataset = bittensor.dataset(batch_size = 10, block_size=20)
            >>> # data.shape[batch_size, block_size]
            >>> data = next(dataset)
    """
    def __new__(
            cls,
            config: 'bittensor.config' = None,
            sequence_length: Optional[int] = None,
            block_size: Optional[int] = None,
            block_size_bytes: Optional[int] = None,
            max_hash_size: Optional[int] = None,
            batch_size: Optional[int] = None,
            num_workers: Optional[int] = None,
            dataset_name: Optional[list] = None,
            max_directories: Optional[int] = None,
            max_datasets: Optional[int] = None,
            save_dataset: Optional[bool] = False,
            load_dataset: Optional[bool] = False,
            no_tokenizer: Optional[bool] = None,
            num_batches: Optional[int] = None,
            buffer_size: Optional[int] = None, 
            buffer_calls_per_update: Optional[int] = None
        ):
        r""" Create and init the GenesisTextDataset class, which handles dataloading from ipfs.
            Args:
                config (:obj:`bittensor.Config`, `optional`): 
                    bittensor.dataset.config()
                sequence_length (:obj:`int`, `optional`):
                    Number of text items to pull for each example.
                block_size (:obj:`int`, `optional`):
                    Number of text items to pull for each example.
                block_size_bytes: 
                    Number of text items to pull for each example in terms of bytes.
                batch_size (:obj:`int`, `optional`):
                    Batch size.
                num_workers (:obj:`int`, `optional`):
                    Number of workers for data loader.
                dataset_name (:obj:`list`, `optional`):
                    Which datasets to use (ArXiv, BookCorpus2, Books3, DMMathematics, EnronEmails, EuroParl, 
                    Gutenberg_PG, HackerNews, NIHExPorter, OpenSubtitles, PhilPapers, UbuntuIRC, YoutubeSubtitles)).
                save_dataset (:obj:`bool`, `optional`):
                    Save the downloaded dataset or not.
                no_tokenizer (:obj:`bool`, `optional`):
                    To return non-tokenized text (EXPERIMENTAL, DO NOT USE)
                num_batches (:obj:`int`, `optional`):
                    The number of batches of data to prepare for the dataloader.
                buffer_size (:obj:`int`, `optional`):
                    The size of the buffer of samples.
                buffer_calls_per_update (:obj:`int`, `optional`):
                    The number of batch calls per update.
        """   

        if config == None: 
            config = dataset.config()

        if isinstance(sequence_length,int):
            block_size = sequence_length
        else:
            logger.warning('WARNING: block_size will be depracted and replaced with sequence_length in future releases.')
            


        config = copy.deepcopy( config )
        config.dataset.block_size_bytes = block_size_bytes if block_size_bytes != None else config.dataset.block_size_bytes
        # TODO replace block_size with sequence_length in future 
        config.dataset.block_size = block_size if block_size != None else config.dataset.block_size
        config.dataset.sequence_length = config.dataset.block_size
        config.dataset.batch_size = batch_size if batch_size != None else config.dataset.batch_size
        config.dataset.num_workers = num_workers if num_workers != None else config.dataset.num_workers
        config.dataset.dataset_name = dataset_name if dataset_name != None else config.dataset.dataset_name
        config.dataset.max_datasets = max_datasets if max_datasets != None else config.dataset.max_datasets
        config.dataset.save_dataset = save_dataset if save_dataset != None else config.dataset.save_dataset
        config.dataset.load_dataset = load_dataset if load_dataset != None else config.dataset.load_dataset
        config.dataset.no_tokenizer = no_tokenizer if no_tokenizer != None else config.dataset.no_tokenizer
        config.dataset.num_batches = num_batches if num_batches != None else config.dataset.num_batches
        config.dataset.max_directories = max_directories if max_directories != None else config.dataset.max_directories
        config.dataset.buffer_size = buffer_size if buffer_size != None else config.dataset.buffer_size
        config.dataset.buffer_calls_per_update = buffer_calls_per_update if buffer_calls_per_update != None else config.dataset.buffer_calls_per_update
        config.dataset.max_hash_size = max_hash_size if max_hash_size != None else config.dataset.max_hash_size

        dataset.check_config( config )

        return dataset_impl.GenesisTextDataset(
            block_size_bytes = config.dataset.block_size_bytes,
            sequence_length = config.dataset.sequence_length,
            batch_size = config.dataset.batch_size,
            max_hash_size= config.dataset.max_hash_size,
            num_workers = config.dataset.num_workers,
            datasets = config.dataset.dataset_name,
            data_dir = config.dataset.data_dir,
            save_dataset = config.dataset.save_dataset,
            load_dataset = config.dataset.load_dataset,
            max_datasets = config.dataset.max_datasets,
            no_tokenizer = config.dataset.no_tokenizer,
            num_batches = config.dataset.num_batches,
            max_directories = config.dataset.max_directories,
            buffer_size=config.dataset.buffer_size,
            buffer_calls_per_update=config.dataset.buffer_calls_per_update,
        )

    @classmethod
    def config(cls) -> 'bittensor.Config':
        """ 
        Get config from the argument parser.
            
        Return: 
            bittensor.Config
        """
        parser = argparse.ArgumentParser()
        dataset.add_args( parser )
        return bittensor.config( parser )

    @classmethod
    def add_args(cls, parser: argparse.ArgumentParser, prefix: str = None ):
        """ Accept specific arguments from parser
        """
        prefix_str = '' if prefix == None else prefix + '.'
        try:
            parser.add_argument('--' + prefix_str + 'dataset.batch_size', type=int, help='Batch size.', default = bittensor.defaults.dataset.batch_size)
            parser.add_argument('--' + prefix_str + 'dataset.block_size', type=int, help='Number of text items to pull for each example..', default = bittensor.defaults.dataset.block_size)
            parser.add_argument('--' + prefix_str + 'dataset.num_workers',  type=int, help='Number of workers for data loader.', default = bittensor.defaults.dataset.num_workers)
            parser.add_argument('--' + prefix_str + 'dataset.dataset_name', type=str, required=False, nargs='*', action='store', help='Which datasets to use (ArXiv, BookCorpus2, Books3, DMMathematics, EnronEmails, EuroParl, Gutenberg_PG, HackerNews, NIHExPorter, OpenSubtitles, PhilPapers, UbuntuIRC, YoutubeSubtitles)).',
                                                                    default = bittensor.defaults.dataset.dataset_name)
            parser.add_argument('--' + prefix_str + 'dataset.data_dir', type=str, help='Where to save and load the data.', default = bittensor.defaults.dataset.data_dir)
            parser.add_argument('--' + prefix_str + 'dataset.save_dataset', action='store_true', help='Save the downloaded dataset or not.', default = bittensor.defaults.dataset.save_dataset)
            parser.add_argument('--' + prefix_str + 'dataset.max_datasets',  type=int, help='Number of datasets to load', default = bittensor.defaults.dataset.max_datasets)
            parser.add_argument('--' + prefix_str + 'dataset.no_tokenizer', action='store_true', help='To return non-tokenized text (EXPERIMENTAL, DO NOT USE)',default=False)
            parser.add_argument('--' + prefix_str + 'dataset.num_batches', type=int, help='The number of data to download each time(measured by the number of batches).', default=bittensor.defaults.dataset.num_batches)
            parser.add_argument('--' + prefix_str + 'dataset.max_directories', type=int, help='Maximum number of directories to consider when loading text from IPFS', default=bittensor.defaults.dataset.max_directories)
            parser.add_argument('--' + prefix_str + 'dataset.block_size_bytes', type=int, help='Number of text bytes items to pull for each example..', default = bittensor.defaults.dataset.block_size_bytes)
            parser.add_argument('--' + prefix_str + 'dataset.buffer_size', type=int, help='The number of samples stored in the buffer during sampling..', default = bittensor.defaults.dataset.buffer_size)
            parser.add_argument('--' + prefix_str + 'dataset.buffer_calls_per_update', type=int, help='The number of calls per replacing 1 element in the buffer.', default = bittensor.defaults.dataset.buffer_calls_per_update)
            parser.add_argument('--' + prefix_str + 'dataset.max_hash_size', type=int, help='The maximum size of the hash of a text file.', default = bittensor.defaults.dataset.max_hash_size)

        except argparse.ArgumentError:
            # re-parsing arguments.
            pass

    @classmethod   
    def help(cls):
        """ Print help to stdout
        """
        parser = argparse.ArgumentParser()
        cls.add_args( parser )
        print (cls.__new__.__doc__)
        parser.print_help()

    @classmethod   
    def add_defaults(cls, defaults):
        """ Adds parser defaults to object from enviroment variables.
        """
        defaults.dataset = bittensor.Config()
        defaults.dataset.batch_size = os.getenv('BT_DATASET_BATCH_SIZE') if os.getenv('BT_DATASET_BATCH_SIZE') != None else 10
        defaults.dataset.block_size = os.getenv('BT_DATASET_BLOCK_SIZE') if os.getenv('BT_DATASET_BLOCK_SIZE') != None else 20
        defaults.dataset.num_workers = os.getenv('BT_DATASET_NUM_WORKERS') if os.getenv('BT_DATASET_NUM_WORKERS') != None else 0
        defaults.dataset.dataset_name = os.getenv('BT_DATASET_DATASET_NAME') if os.getenv('BT_DATASET_DATASET_NAME') != None else 'default'
        defaults.dataset.data_dir = os.getenv('BT_DATASET_DATADIR') if os.getenv('BT_DATASET_DATADIR') != None else os.path.expanduser('~/./bittensor/data')
        defaults.dataset.save_dataset = os.getenv('BT_DATASET_SAVE_DATASET') if os.getenv('BT_DATASET_SAVE_DATASET') != None else False
        defaults.dataset.max_datasets = os.getenv('BT_DATASET_MAX_DATASETS') if os.getenv('BT_DATASET_MAX_DATASETS') != None else 3
        defaults.dataset.num_batches = os.getenv('BT_DATASET_NUM_BATCHES') if os.getenv('BT_DATASET_NUM_BATCHES') != None else 500
        defaults.dataset.max_directories = os.getenv('BT_DATASET_MAX_DIRECTORIES') if os.getenv('BT_DATASET_MAX_DIRECTORIES') != None else 250
        defaults.dataset.buffer_size = os.getenv('BT_DATASET_BUFFER_SIZE') if os.getenv('BT_DATASET_BUFFER_SIZE') != None else 1000
        defaults.dataset.buffer_calls_per_update = os.getenv('BT_DATASET_BUFFER_CALLS_PER_UPDATE') if os.getenv('BT_DATASET_BUFFER_CALLS_PER_UPDATE') != None else 100
        defaults.dataset.max_hash_size = os.getenv('BT_DATASET_MAX_HASH_SIZE') if os.getenv('BT_DATASET_MAX_HASH_SIZE') != None else 100_000
        defaults.dataset.block_size_bytes = os.getenv('BT_DATASET_BLOCK_SIZE_BYTES') if os.getenv('BT_DATASET_BLOCK_SIZE_BYTES') != None else 1500


    @classmethod
    def check_config( cls, config: 'bittensor.Config' ):
        """ Check config for batch size, block size, corpus size, num_workers and dataset
        """
        assert config.dataset.batch_size > 0, 'Batch size must be larger than 0'
        assert config.dataset.block_size > 0, 'Block size must be larger than 0'
        assert config.dataset.num_workers >= 0, 'num_workers must be equal to or larger than 0'
        assert isinstance(config.dataset.save_dataset, bool) , 'save_dataset must be True/False only'
