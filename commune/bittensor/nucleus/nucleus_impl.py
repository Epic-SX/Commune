
import asyncio 
import torch
asyncio.set_event_loop(asyncio.new_event_loop())
import os,sys
sys.path.append(os.getenv('PWD'))
import streamlit as st

import argparse
import math
import bittensor
import torch
from torch import nn
import torch.nn.functional as F
from types import SimpleNamespace
from typing import Tuple, Optional
import transformers
from transformers import AutoModel,AutoTokenizer,AutoConfig, AutoModelForCausalLM
from torch.nn.utils.rnn import pad_sequence
from bittensor.utils.tokenizer_utils import prep_tokenizer, get_translation_map, translate_logits_to_probs_std, \
    translate_special_token_text, pad_offsets, topk_token_phrases, compact_topk_token_phrases
from loguru import logger; logger = logger.opt(colors=True)
import sys
import time
import datetime
from threading import Lock
from datetime import datetime,timedelta
import wandb
import pandas
import torch
import torch.nn.functional as F
from torch.nn.utils import clip_grad_norm_


class Nucleus(torch.nn.Module):
    def __init__(self, 

                model: 'Model' = None,
                tokenizer:'huggingfadce.tokenizer' = None,

                padding: bool =None, 
                interpolate: bool =None,
                inter_degree: str = None,
                mapping_function:'Callable' = None,
                token_remap:'Callable' = None,

                ## All of the bittensor sutff
                config: 'bittensor.config' = None,
                subtensor: 'bittensor.subtensor'= None,
                wallet: 'bittensor.wallet'= None,
                metagraph: 'bittensor.metagraph'= None,
                axon: 'bittensor.axon'= None,
                
                # Enabling synapses
                lasthidden:bool = None,
                causallm:bool = None,
                causallmnext: bool = None,
                seq2seq: bool = None,

                # Stake per synapse
                lasthidden_stake:float = None,
                causallm_stake:float = None,
                causallmnext_stake: float = None,
                seq2seq_stake: float = None,

                port:int = None,
                ):

        r"""" Creates a server that serves up a pretrained miner on the bittensor network
        Args:
                config (:obj:`bittensor.Config`, `required`): 
                    bittensor.server.config()

                model (:obj:string , `object`):
                    The model.
                padding (:obj:bool, `optional`):
                    If the server should pad out to match the hidden units that the bittensor network is using
                    If set to False, it will instead create a mapping layer to do the same thing.
                interpolate (:obj:bool, `optional`):
                    If the server should interpolate between sequence length differences.
                    If set to false, there should be a mapping function that takes care of the differnces
                inter_degree (:obj:str, `optional`):
                    The Interpolate algorithm (nearest | linear | bilinear | bicubic | trilinear | area)
                model (:obj:torch.module, `optional`):
                    Overrides the huggingface pretrained model with your own pretrained model
                tokenizer (:obj:huggingface.tokenizer, `optional`):
                    Overrides the huggingface tokenizer with your tokenizer
                mapping_function (:obj:Callable, `optional`):
                    Custom mapping function that maps between sequence length differences between tokenizers
                token_remap (:obj:Callable, `optional`):
                    Custom function that maps between tokenizers (defaults to self.remapping_token)
        """
        super().__init__()
        config = config if config else  self.default_config()

        config.neuron.lasthidden = lasthidden if lasthidden != None else config.neuron.lasthidden
        config.neuron.causallm = causallm if causallm != None else config.neuron.causallm
        config.neuron.causallmnext = causallmnext if causallmnext is not None else config.neuron.causallmnext
        config.neuron.seq2seq = seq2seq if seq2seq != None else config.neuron.seq2seq

        config.neuron.lasthidden_stake = lasthidden_stake if lasthidden_stake != None else config.neuron.lasthidden_stake
        config.neuron.causallm_stake = causallm_stake if causallm_stake != None else config.neuron.causallm_stake
        config.neuron.causallmnext_stake = causallmnext_stake if causallmnext_stake is not None else config.neuron.causallmnext_stake
        config.neuron.seq2seq_stake = seq2seq_stake if seq2seq_stake != None else config.neuron.seq2seq_stake


        self.std_tokenizer = bittensor.tokenizer()
        self.device = config.neuron.device
        self.model = model

        if hasattr(self.model, 'tokenizer'):
            self.tokenizer = self.model.tokenizer
        elif isinstance(tokenizer, str):
            self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer)
        elif tokenizer is None:
            self.tokenizer = bittensor.tokenizer()
        
        self.tokenizer = prep_tokenizer(self.tokenizer, self.std_tokenizer)
        self.to_translation_map = get_translation_map(self.tokenizer, self.std_tokenizer)
        self.from_translation_map = get_translation_map(self.std_tokenizer, self.tokenizer)
        self.split_map_cache = {}
        #parameters of the models
        self.final_dim =  bittensor.__network_dim__

        self.padding = padding if padding != None else config.neuron.padding
        self.interpolate = interpolate if interpolate != None else config.neuron.interpolate
        self.inter_degree = inter_degree if inter_degree != None else config.neuron.inter_degree
        self.mapping_function= mapping_function
        self.token_remap = token_remap if token_remap is not None else self.remapping_token

        self.timecheck_dicts = {bittensor.proto.RequestType.FORWARD:{}, bittensor.proto.RequestType.BACKWARD:{}}
        self.loss_fct = torch.nn.CrossEntropyLoss()
    
        #checking if the parameters of the server makes sense
        self.check()

        # Create Subtensor connection
        self.subtensor = bittensor.subtensor(config = config) if subtensor == None else subtensor
        
        # Load/Create our bittensor wallet.
        self.wallet = wallet if wallet else bittensor.wallet( config = config ).create()
        self.wallet.reregister(subtensor=subtensor)

        # Load/Sync/Save our metagraph.
        self.metagraph = metagraph if metagraph else bittensor.metagraph ( subtensor = subtensor)
        self.metagraph.load().sync().save()

        self.mutex = Lock()
        self.config = config
 
        self.axon = bittensor.axon(
            config = self.config,
            wallet = self.wallet,
            synapse_checks=self.synapse_check,
            synapse_last_hidden =  self.forward_last_hidden if self.config.neuron.lasthidden else None,
            synapse_causal_lm = self.forward_casual_lm if self.config.neuron.causallm else None,
            synapse_causal_lm_next = self.forward_casual_lm_next if self.config.neuron.causallmnext else None,
            synapse_seq_2_seq =  self.forward_seq_2_seq if self.config.neuron.seq2seq else None, 
            blacklist = self.blacklist if not self.config.neuron.disable_blacklist else None,
            priority = self.priority if not self.config.neuron.disable_priority else None,
            port = port
        )



    def remapping_token(self, token_batch, std_tokenizer=None, return_offsets_mapping=False):
        r""" Tokenizer remapping; decodes the message and then remaps the message using a new tokenizer
            Args:
                token_batch ( :obj:`torch.LongTensor`, `required`):
                    token_batch to be retokenized, [batch_size, sequence_len]
                std_tokenizer ( :obj:`transformers.Tokenizer`, `optional`):
                    The standard tokenizer which was used to tokenize the input.
                return_offsets_mapping ( :obj:`bool`, `required`):
                    Return offsets_mapping in tokenization to delineate token segment positions.
        """
        if std_tokenizer is None:
            std_tokenizer = self.std_tokenizer

        text_batch = std_tokenizer.batch_decode(token_batch)  # decode tokens to original text
        result = translate_special_token_text(text_batch, std_tokenizer, self.tokenizer)  # translate special tokens
        to_text_batch, from_offsets_batch, to_offsets_batch, pad_offsets_batch = result

        tokens = self.tokenizer(to_text_batch, padding=True, truncation=True, max_length=token_batch.size(1), return_tensors='pt',
                                add_special_tokens=False).to(self.device)  # assume tokenizer.padding_side = 'left'

        if return_offsets_mapping:  # get offsets_mapping in tokenization to delineate token segment positions
            server_tokens = self.tokenizer(to_text_batch, return_offsets_mapping=True, add_special_tokens=False)
            std_tokens = std_tokenizer(text_batch, return_offsets_mapping=True)  # encode again to get offsets mapping

            # pad offsets so that special token offset widths match for continued correct alignment
            tokens['offset_mapping'] = pad_offsets(server_tokens['offset_mapping'], to_offsets_batch, pad_offsets_batch)
            tokens['offset_mapping_std'] = pad_offsets(std_tokens['offset_mapping'], from_offsets_batch,
                                                       pad_offsets_batch)
        return tokens





    def forward(self, inputs, tokenizer=None):
        """
            Forward pass through the whole server model. Returns the loss and decoded predictions.

            Args:
                inputs ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.
                tokenizer (:obj:'huggingface.tokenizer', optional):
                    The tokenizer which was used to tokenize the inputs
             Returns:
                loss (:obj:`torch.FloatTensor`):
                    MLM loss from the inputs
                decoded_targets (:obj:`torch.FloatTensor`):
                    Decoded predictions of the next token in the sentence.

        """
        message, model_output, decoded_targets = self.local_forward(inputs, tokenizer)
        shift_logits = decoded_targets[..., :-1, :].contiguous()
        shift_labels = inputs[..., 1:].contiguous()
        loss = self.loss_fct( shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1) )

        return loss, decoded_targets

    def local_forward(self, token_batch, tokenizer=None, encode_len=bittensor.__network_dim__, model_output = None):
        r""" Forward pass through the pretrained model and possible mappings between hidden units.
             The response tensor should be the hidden units computed using the local context and
             with shape: [batch_size, sequence_len, __vocab_size__].

            Args:
                token_batch ( :obj:`torch.LongTensor`, `required`):
                    torch inputs to be forward processed, [batch_size, sequence_len]
                tokenizer ( huggingface.tokenizer, `optional`):
                    The tokenizer which was used to tokenize the inputs
                encode_len ( :obj:`int`, `optional`):
                    logit encoding length, default bittensor.__network_dim__ length
                model_output (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `optional`):
                    The output of huggingface auto model.

            Returns:
                model_outputs (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `required`):
                    The output of huggingface auto model.
                
                logits (:obj:`torch.FloatTensor`):
                    The nucleus's logit outputs as a torch tensor of shape [batch_size, sequence_len, __vocab_size__]
        """
        tokens = self.token_remap(token_batch, std_tokenizer=tokenizer, return_offsets_mapping=True)  # remap to server tokenizer
        if model_output == None:
            if self.config.neuron.local_train:
                model_output = self.pre_model(input_ids=tokens['input_ids'],
                                                attention_mask=tokens['attention_mask'],
                                                output_hidden_states=True)
            else:
                with torch.no_grad():
                    model_output = self.pre_model(input_ids=tokens['input_ids'],
                                                    attention_mask=tokens['attention_mask'],
                                                    output_hidden_states=True)

        return None, model_output, model_output.logits

    def encode_forward_causallmnext(self, token_batch, std_tokenizer=None, topk: int = 4096, model_output=None):
        r"""
        Forward pass through the pretrained model and select topk tokenizer logits and retokenize with std_tokenizer,
        then compact new token phrases and probabilities
        into 1-D tensor [ >= batch_size * (2 * topk + 1)] prob + at least 1 token per phrase + floor_prob.
        The floor probability is the mean probability of token phrases not captured in topk, required since
        the server tokenizer vocab_size may not be known to the receiver/validator.

            Args:
                token_batch ( :obj:`torch.LongTensor`, `required`):
                    torch inputs to be forward processed, [batch_size, std_sequence_len].
                std_tokenizer ( :obj:`PreTrainedTokenizerBase`, `optional`):
                    The standard tokenizer which was used to tokenize the inputs.
                topk ( :obj:`int`, `optional`):
                    Amount of std_tokenized server phrases with highest probability to produce.
                model_output (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `optional`):
                    The output of transformers AutoModel.

            Returns:
                model_outputs (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `required`):
                    The output of transformers AutoModel.
                topk_tensor (:obj:`torch.Tensor`, `required`):
                    [batch_size, (topk + 1), max_len] tensor includes topk token probabilities (prob_k) + floor_prob
                    in first column with gradients attached, with std_tokens in remaining columns with ignore_index padding.
                    Content structure:
                    [[[prob_k=0_b=0, tok_0_k=0_b=0, tok_1_k=0_b=0, ..., ignore_index?],
                      [prob_k=1_b=0, tok_0_k=1_b=0, tok_1_k=1_b=0, ..., ignore_index?],
                      [...],
                      [prob_floor_b=0, ignore_index, ..., ignore_index]],
                     [[prob_k=0_b=1, tok_0_k=0_b=1, tok_1_k=0_b=1, ..., ignore_index?],
                      [prob_k=1_b=1, tok_0_k=1_b=1, tok_1_k=1_b=1, ..., ignore_index?],
                      [...],
                      [prob_floor_b=1, ignore_index, ..., ignore_index]],
                     [...]]
        """
        transformers.set_seed(0)
        transformers.enable_full_determinism(0)
        
        if std_tokenizer is None:
            std_tokenizer = self.std_tokenizer

        tokens = self.token_remap(token_batch, std_tokenizer)


        if model_output is None:
            model_output = self.model(input_ids=tokens['input_ids'],
                                            attention_mask=tokens['attention_mask'],
                                            output_hidden_states=True)

        # model_output.logits: [batch_size, sequence_len, server_vocab_size]
        last_logits = model_output.logits[:, -1, :]  # [batch_size] server prediction of continuation, right-aligned

        # Select topk tokenizer logits and retokenize with std_tokenizer,
        # then compact new token phrases and probabilities into 1-D tensor
        topk_tensor = topk_token_phrases(last_logits, self.tokenizer, topk=topk)  # [batch_size, (topk + 1), max_len]

        message = f'Hello from Deepseed'

        return message, model_output, topk_tensor


    def forward_casual_lm_next(self, inputs_x: torch.FloatTensor, synapse, model_output=None):
        with self.mutex:
            message, model_output, topk_token_phrases = self.encode_forward_causallmnext(inputs_x,
                                                                                        topk=synapse.topk,
                                                                                        model_output=model_output)
        # topk_token_phrases: [sum_b(sum_k(len(phrase_k) + 1)_b)] contains topk token phrases and probabilities
        #   Compacted 1-D tensor >= batch_size * (2 * topk + 1)
        return message, model_output, topk_token_phrases


    def get_loss_fct(self, logits: torch.FloatTensor, labels: torch.LongTensor) -> torch.FloatTensor:
        """
        Calculate loss_fct, CausalLM loss, next-token prediction loss.
            Args:
                logits (:obj:`torch.FloatTensor`, `required`):
                    [batch_size, sequence_len, bittensor.__network_dim__]
                labels (:obj:`torch.LongTensor`, `required`):
                    [batch_size, sequence_len]

            Returns:
                loss (:obj:`torch.FloatTensor`):
                    scalar
        """
        shift_logits = logits[..., :-1, :]
        shift_labels = labels[..., 1:]
        loss = self.loss_fct(shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1))

        return loss

    def check(self):
        r"""Checks the server settings
        """
        if self.interpolate == False:
            assert self.mapping_function != None, 'Incorrect Settings; needs atleast one mapping function for sequence length changes'


    @staticmethod
    def default_config ():
        parser = argparse.ArgumentParser()
        parser.add_argument('--config', type=str, help='If set, defaults are overridden by passed file.')

        # ML model arguements
        parser.add_argument('--neuron.device', type=str, help='miner default training device cpu/cuda', default=("cuda" if torch.cuda.is_available() else "cpu"))
        parser.add_argument('--neuron.padding', action='store_false', help='To pad out final dimensions',default=True)
        parser.add_argument('--neuron.interpolate', action='store_false', help='To interpolate between sentence length',default=True)
        parser.add_argument('--neuron.inter_degree', type=str, help='Interpolate algorithm (nearest | linear | bilinear | bicubic | trilinear | area)', default='nearest')
        parser.add_argument('--neuron.autocast',  action='store_true', help='(experimental) autocasts the model to float16. Must require cuda', default=False)
        
        # Miner arguements
        parser.add_argument('--neuron.name', type=str, help='Trials for this miner go in miner.root / (wallet_cold - wallet_hot) / miner.name ', default='core_server')
        parser.add_argument('--neuron.restart', action='store_true', help='If True, train the neuron from the beginning', default=False)
        parser.add_argument('--neuron.no_set_weights', action='store_true', help='If True, the model does not set weights.', default=False)
        parser.add_argument('--neuron.blacklist.stake', type=float, help='Amount of stake (tao) in order not to get blacklisted', default=10)
        parser.add_argument('--neuron.blocks_per_epoch', type=int, help='Blocks per epoch', default=10)
        parser.add_argument('--neuron.blacklist.time', type=int, help='how often a peer can query you (seconds) ', default=1)
        parser.add_argument('--neuron.blocks_per_set_weights', type=float, help='how often to set weights', default=-1)
        parser.add_argument('--neuron.metagraph_sync', type=float, help='how often to sync the metagraph', default=100000)
        parser.add_argument('--neuron.blacklist_allow_non_registered', action='store_true', help='''If true, allow non-registered peers''', default=False)
        parser.add_argument('--neuron.disable_blacklist', action='store_true', help='Turns off blacklisting', default=False)
        parser.add_argument('--neuron.disable_priority', action='store_true', help='Turns off priority threadpool', default=False)

        # Synapse Arguements
        parser.add_argument('--neuron.lasthidden', action='store_false', help='To turn off last hidden synapse', default=False)
        parser.add_argument('--neuron.causallm', action='store_false', help='To turn off causallm synapse', default=False)
        parser.add_argument('--neuron.causallmnext', action='store_false', help='To turn off causallmnext synapse', default=True)
        parser.add_argument('--neuron.seq2seq', action='store_false', help='To turn off seq2seq synapse', default=False)
        parser.add_argument('--neuron.lasthidden_stake', type = float, help='the amount of stake to run last hidden synapse',default=0)
        parser.add_argument('--neuron.causallm_stake',  type = float, help='the amount of stake to run causallm synapse',default=0)
        parser.add_argument('--neuron.causallmnext_stake', type=float, help='the amount of stake to run causallmnext synapse', default=0)
        parser.add_argument('--neuron.seq2seq_stake',  type = float, help='the amount of stake to run seq2seq synapse',default=0)


        bittensor.wallet.add_args( parser )
        bittensor.axon.add_args( parser )
        bittensor.subtensor.add_args( parser )
        bittensor.logging.add_args( parser )
        bittensor.wandb.add_args(parser)
        bittensor.prioritythreadpool.add_args( parser )
        bittensor.dataset.add_args( parser )
        bittensor.metagraph.add_args( parser )
        return bittensor.config( parser )


    
    def synapse_check(self, synapse, hotkey):
        """
            Custom synapse function to protect certain synapse functions depending on the stake and weight.
            Certain synapses require more compute than others. For instance, TEXT_SEQ_2_SEQ requires a significantly
            more commitment by the server than a requeset for TEXT_CAUSAL_LM_NEXT.

            Args:
                synapse (:obj:`bittensor.proto.SynapseArgs`, `required`): 
                    The proto message that contains additional args for individual synapse functions
                hotkey (:obj:`torch.FloatTensor`, `required`):
                    The hotkey that sent the request

        """
        ## Uid that sent the request
        incoming_uid = metagraph.hotkeys.index(hotkey)
        if synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_LAST_HIDDEN_STATE:
            
            if metagraph.S[incoming_uid] < self.config.neuron.lasthidden_stake:
                return False
            
        elif synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_CAUSAL_LM:

            if metagraph.S[incoming_uid] < self.config.neuron.causallm_stake:
                return False

        elif synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_CAUSAL_LM_NEXT:

            if metagraph.S[incoming_uid] < self.config.neuron.causallmnext_stake:
                return False

        elif synapse.synapse_type == bittensor.proto.Synapse.SynapseType.TEXT_SEQ_2_SEQ:

            if (metagraph.S[incoming_uid] < self.config.neuron.seq2seq_stake) and (metagraph.S[incoming_uid,  uid]):
                return False     
        else:
            return False

        return True

    
    def priority(self, pubkey:str, request_type:bittensor.proto.RequestType, inputs_x) -> float:
        r"""Calculates the priority on requests based on stake and size of input
            Args:
                pubkey ( str, `required`):
                    The public key of the caller.
                inputs_x ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.
                request_type ( bittensor.proto.RequestType, `required`):
                    the request type ('FORWARD' or 'BACKWARD').
        """
        try:        
            uid = self.metagraph.hotkeys.index(pubkey)
            priority = self.metagraph.S[uid].item()
        
        except:
            # zero priority for those who are not registered.
            priority =  0

        return priority

    def blacklist(self, pubkey:str, request_type:bittensor.proto.RequestType) -> bool:
        r"""Axon security blacklisting, used to blacklist message from low stake members
            Args:
                pubkey ( str, `required`):
                    The public key of the caller.
                request_type ( bittensor.proto.RequestType, `required`):
                    the request type ('FORWARD' or 'BACKWARD').
        """
        # Check for registrations

        def registration_check():
            # If we allow non-registered requests return False = not blacklisted.
            is_registered = pubkey in self.metagraph.hotkeys
            if not is_registered:
                if self.config.neuron.blacklist_allow_non_registered:
                    return False

                raise Exception('Registration blacklist')

        # Check for stake
        def stake_check() -> bool:
            # Check stake.
            uid = self.metagraph.hotkeys.index(pubkey)
            if self.metagraph.S[uid].item() < self.config.neuron.blacklist.stake:

                raise Exception('Stake blacklist')
            return False

        # Check for time
        def time_check():
            current_time = datetime.now()
            timecheck = self.timecheck_dicts[request_type]
            if pubkey in timecheck.keys():
                prev_time = timecheck[pubkey]
                if current_time - prev_time >= timedelta(seconds=self.config.neuron.blacklist.time):
                    timecheck[pubkey] = current_time
                else:
                    timecheck[pubkey] = current_time
                    raise Exception('Time blacklist')
            else:
                timecheck[pubkey] = current_time
        
            return False

        # Black list or not
        try:
            registration_check()
            time_check()
            stake_check()            
            return False
        except Exception as e:
            return True




    def serve(self):

        # Create our axon server and subscribe it to the network.
        self.axon.start().serve(subtensor=self.subtensor)

        last_set_block = self.subtensor.get_current_block()
        blocks_per_epoch = self.subtensor.blocks_per_epoch if self.config.neuron.blocks_per_epoch == -1 else self.config.neuron.blocks_per_epoch
        blocks_per_set_weights = self.subtensor.blocks_per_epoch if self.config.neuron.blocks_per_set_weights == -1 else self.config.neuron.blocks_per_set_weights

        while True:
            iteration = 0
            local_data = {}
            nn = self.subtensor.neuron_for_pubkey(self.wallet.hotkey.ss58_address)
            uid = self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address )
            current_block = self.subtensor.get_current_block()
            end_block = current_block + self.config.neuron.blocks_per_epoch

            while end_block >= current_block:
                time.sleep(12)
                current_block = self.subtensor.get_current_block()

            
            wandb_data = {            
                'stake': nn.stake,
                'rank': nn.rank,
                'trust': nn.trust,
                'consensus': nn.consensus,
                'incentive': nn.incentive,
                'emission': nn.emission,
            }
        

            if current_block - last_set_block > blocks_per_set_weights:
                bittensor.__console__.print('[green]Current Status:[/green]', {**wandb_data, **local_data})
                self.metagraph.sync()
                last_set_block = current_block
                if not self.config.neuron.no_set_weights:
                    try: 
                        bittensor.__console__.print('[green]Current Status:[/green]', {**wandb_data, **local_data})
                        # Set self weights to maintain activity.
                        # --- query the chain for the most current number of peers on the network
                        chain_weights = torch.zeros(self.subtensor.n)
                        chain_weights [ uid ] = 1 
                        did_set = self.subtensor.set_weights(
                            uids=torch.arange(0,self.subtensor.n),
                            weights = chain_weights,
                            wait_for_inclusion = False,
                            wallet = wallet,
                        )
                        if did_set:
                            logger.success('Successfully set weights on the chain')
                        else:
                            logger.error('Failed to set weights on chain. (Timeout)')
                        
                    except Exception as e:
                        logger.error('Failure setting weights on chain with error: {}', e)


    run = serve


    @staticmethod
    def check_config( config: 'bittensor.Config' ):
        r""" Checks/validates the config namespace object.
        """
        bittensor.logging.check_config( config )
        bittensor.wallet.check_config( config )
        bittensor.subtensor.check_config( config )
        bittensor.metagraph.check_config( config )
        bittensor.dataset.check_config( config )
        bittensor.axon.check_config( config )
        bittensor.wandb.check_config( config )
        bittensor.prometheus.check_config( config )
        full_path = os.path.expanduser('{}/{}/{}/{}'.format( config.logging.logging_dir, config.wallet.get('name', bittensor.defaults.wallet.name), config.wallet.get('hotkey', bittensor.defaults.wallet.hotkey), config.neuron.name ))
        config.neuron.full_path = os.path.expanduser(full_path)
        if not os.path.exists(config.neuron.full_path):
            os.makedirs(config.neuron.full_path)


    
    def encode_forward(self,inputs,tokenizer=None, model_output = None):
        r""" Forward pass through the pretrained model and possible mappings between hidden units. 
             The response tensor should be the hidden units computed using the local context and with shape: [batch_size, sequence_len, __network_dim__].

            Args:
                inputs ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.
                tokenizer ( huggingface.tokenizer, `optional`):
                    The tokenizer which was used to tokenize the inputs
                model_outputs (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `optional`):
                    The output of huggingface auto model.

            Returns:
                model_outputs (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `required`):
                    The output of huggingface auto model.
                    
                encoded_hidden (:type:`torch.Tensor`, `required`)
                    The hidden layer output as a torch tensor of shape [batch_size, sequence_len, __network_dim__ ]
        """
        transformers.set_seed(0)
        transformers.enable_full_determinism(0)

        input_shape = inputs.shape
        seq_len = input_shape[1]
        tokens = self.token_remap(inputs, tokenizer)  # remap to server tokenizer

        model_output = self.model(input_ids=tokens['input_ids'],
                                        attention_mask=tokens['attention_mask'],
                                        output_hidden_states=True)


        pre_hidden = model_output.hidden_states[-1] 
        model_hidden_seq_len = pre_hidden.shape[1]


        if self.interpolate and seq_len != model_hidden_seq_len:
            interpolated_pre_hidden= F.interpolate(pre_hidden.unsqueeze(1),size=[sen_len[1],pre_hidden.size()[2]],mode=self.inter_degree).squeeze(1)
        elif self.mapping_function:
            interpolated_pre_hidden = self.mapping_function(pre_hidden)
        else:
            interpolated_pre_hidden = pre_hidden

        if self.padding:
            padding_l = (self.final_dim-self.pre_dimension)//2
            padding_r = (self.final_dim-self.pre_dimension) - padding_l
            encoded_hidden = F.pad(interpolated_pre_hidden, (padding_l, padding_r),  "constant", 0)
        else:
            assert self.mapping != None
            encoded_hidden = self.mapping(interpolated_pre_hidden)

        return None, model_output, encoded_hidden

    def encode_forward_causallm(self, token_batch, tokenizer=None, encode_len=bittensor.__network_dim__, model_output=None):
        r""" Forward pass through the pretrained model and possible mappings between hidden units.
             The response tensor should be the hidden units computed using the local context and
             with shape: [batch_size, sequence_len, __vocab_size__].

            Args:
                token_batch ( :obj:`torch.LongTensor`, `required`):
                    torch inputs to be forward processed, [batch_size, sequence_len]
                tokenizer ( huggingface.tokenizer, `optional`):
                    The tokenizer which was used to tokenize the inputs
                encode_len ( :obj:`int`, `optional`):
                    logit encoding length, default bittensor.__network_dim__ length
                model_output (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `optional`):
                    The output of huggingface auto model.

            Returns:
                model_outputs (:obj:`transformers.modeling_outputs.BaseModelOutputWithCrossAttentions`, `required`):
                    The output of huggingface auto model.
                
                logits_std (:obj:`torch.FloatTensor`):
                    The nucleus's logit outputs as a torch tensor of shape [batch_size, sequence_len, __vocab_size__]
        """
        transformers.set_seed(0)
        transformers.enable_full_determinism(0)

        tokens = self.token_remap(token_batch, std_tokenizer=tokenizer, return_offsets_mapping=True)  # remap to server tokenizer

        def _forward(_model_output=model_output):
            if _model_output is None:
                # transformer models like gerpt2 typically perform worse with left-side attention mask, so turning it off
                _model_output = self.model(input_ids=tokens['input_ids'],
                                                #attention_mask=tokens['attention_mask'],
                                               output_hidden_states=True)
            pre_logits = _model_output.logits  # [batch_size, sequence_len, self.tokenizer.vocab_len]

            probs_std = translate_logits_to_probs_std(pre_logits,
                                                      tokens['offset_mapping'], tokens['offset_mapping_std'],
                                                      self.tokenizer, self.std_tokenizer,
                                                      self.split_map_cache,
                                                      self.to_translation_map, self.from_translation_map,
                                                      tokens['input_ids'], token_batch)
            probs_std = probs_std.to(self.device)
            logits_std = torch.log(probs_std + 1e-40)

            #removing the loss calculation for stablity testing
            original_loss = self.get_loss_fct(pre_logits, tokens['input_ids']).item()
            translated_loss = self.get_loss_fct(logits_std, token_batch).item()
            message = f'Loss: {original_loss:.2f} → {translated_loss:.2f}'
            
            return message, _model_output, logits_std

        if self.config.neuron.remote_train:
            return _forward()  # track gradients for training

        with torch.no_grad():
            return _forward()  # no gradients


    def forward_last_hidden(self, inputs_x:torch.FloatTensor, synapse, model_output = None):
        with self.mutex:
            message, model_output, hidden = self.encode_forward(inputs_x.to(model.device), model_output=model_output)
        return message, model_output, hidden

    def forward_casual_lm(self,inputs_x:torch.FloatTensor, synapse, model_output = None):
        with self.mutex:
            message, model_output, logits = self.encode_forward_causallm(inputs_x.to(model.device), model_output=model_output)
        return message, model_output, logits

    def forward_casual_lm_next(self, inputs_x: torch.FloatTensor, synapse, model_output=None):
        with self.mutex:
            message, model_output, topk_token_phrases = self.encode_forward_causallmnext(inputs_x.to(model.device),
                                                                                        topk=synapse.topk,
                                                                                        model_output=model_output)
        # topk_token_phrases: [sum_b(sum_k(len(phrase_k) + 1)_b)] contains topk token phrases and probabilities
        #   Compacted 1-D tensor >= batch_size * (2 * topk + 1)
        return message, model_output, topk_token_phrases


    def forward_seq_2_seq(self, inputs_x:torch.FloatTensor, synapse, model_output = None):
        tokens = self.token_remap(inputs_x.to(model.device))
        output = self.generate(
            input_ids=tokens['input_ids'],
            attention_mask=tokens['attention_mask'],
            max_length=max(tokens['input_ids'].shape[1] + 1, synapse.num_to_generate),
            num_beams=synapse.num_beams,
            no_repeat_ngram_size=synapse.no_repeat_ngram_size,
            early_stopping = synapse.early_stopping,
            do_sample=synapse.do_sample,
            top_p=synapse.top_p,
            num_return_sequences=synapse.num_return_sequences,
            temperature = synapse.temperature,
            repetition_penalty = synapse.repetition_penalty,
            length_penalty = synapse.length_penalty,
            max_time = synapse.max_time,
            num_beam_groups = synapse.num_beam_groups,
        )
        raw_texts = [self.tokenizer.decode(out) for out in output]
        tokens = [self.std_tokenizer.encode(raw_text, return_tensors="pt")[:,:synapse.num_to_generate].view(-1) for raw_text in raw_texts]
        bittensor_output = pad_sequence(tokens, batch_first=True)
        return None, model_output, bittensor_output

    @staticmethod
    def test_remote_server():
        from commune.model.remote import RemoteModelClient
        module = Nucleus(model=RemoteModelClient())
        raw_text = ['hey whats up', 'hey sup']
        token_batch = module.std_tokenizer(raw_text, max_length=64, truncation=True, padding="max_length", return_tensors="pt")["input_ids"]
        st.write(module.encode_forward_causallmnext(token_batch=token_batch))


if __name__ == "__main__":
    # Nucleus.test_deepseed()
    Nucleus.test_remote_server(key='default.default', port=8093)
    # Nucleus.test_remote_server()
