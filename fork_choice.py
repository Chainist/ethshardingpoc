from blocks import Block
from config import SHARD_IDS
from typing import List, Dict

import copy

# Returns children of a block tht are not in the filter
def filtered_children(block, blocks, block_filter):
    children = []
    for b in blocks:
        if b.prevblock is not None:
            if b.prevblock == block and b not in block_filter:
                children.append(b)
    return children

# Returns an unfiltered child with maximum score
# The score of a block is the total weight of weighted blocks that agree
def best_child(block, blocks, weighted_blocks, block_filter):
    children = filtered_children(block, blocks, block_filter)

    # If there are no children, we just return the function's input
    if len(children) == 0:
        return block

    # scorekeeping stuff
    max_score = 0
    winning_child = children[0]

    for c in children:

        # calculates sum of agreeing weight
        score = 0
        for b in weighted_blocks.keys():
            if b.is_in_chain(c):
                score += weighted_blocks[b]

        # check if this is a high score
        if score > max_score:
            winning_child = c
            max_score = score

    return winning_child

# Filtered GHOST: like GHOST but it ignores blocks in "block_filter"
def fork_choice(starting_block, blocks, weighted_blocks, block_filter=[]) -> Block:
    assert starting_block not in block_filter, "expected starting block to not be filtered"

    # This loop replaces this_block with this_block's best filtered child
    this_block = starting_block
    next_block = best_child(this_block, blocks, weighted_blocks, block_filter)
    while (next_block != this_block):
        this_block = next_block
        next_block = best_child(this_block, blocks, weighted_blocks, block_filter)

    return this_block

def is_block_filtered(shard_ID, parent_ID, b, starting_blocks, blocks, weighted_blocks, tips_cache):
    new_starting_blocks = copy.copy(starting_blocks)
    # TODO: we don't want to always start from genesis, Vlad fix me!
    #new_starting_blocks[parent_ID] = b.sources[parent_ID]
    parent_shard_fork_choice = sharded_fork_choice(parent_ID, new_starting_blocks, blocks, weighted_blocks, tips_cache)

    # FILTER BLOCKS THAT DONT AGREE WITH MOST RECENT SOURCE
    if parent_shard_fork_choice.sources[b.shard_ID] is not None:
        if not parent_shard_fork_choice.sources[b.shard_ID].is_in_chain(b):
            if not b.is_in_chain(parent_shard_fork_choice.sources[b.shard_ID]):
                return True
    # --------------------------------------------------------------------#


    # FILTER BLOCKS WITH ORPHANED SOURCES
    if b.sources[parent_ID] is not None:
        if not parent_shard_fork_choice.is_in_chain(b.sources[parent_ID]):
            return True
    # --------------------------------------------------------------------#


    # FILTER BLOCKS WITH ORPHANED BASES
    filtered = False
    for m in b.newly_sent()[parent_ID]:
        if not parent_shard_fork_choice.is_in_chain(m.base):
            return True
    # --------------------------------------------------------------------#


    # FILTER BLOCKS THAT FAIL TO RECEIVE MESSAGES FROM PARENT ON TIME
    filtered = False
    for m in parent_shard_fork_choice.sent_log.log[b.shard_ID]:  # inefficient
        if m in b.received_log.log[parent_ID]:
            continue
        if b.height >= m.base.height + m.TTL:  # EXPIRY CONDITION
            return True
    # --------------------------------------------------------------------#


    # FILTER BLOCKS THAT SEND MESSAGES THAT WERE NOT RECEIVED IN TIME
    filtered = False
    for m in b.sent_log.log[parent_ID]:  # inefficient
        if m in parent_shard_fork_choice.received_log.log[b.shard_ID]:
            continue
        if parent_shard_fork_choice.height >= m.base.height + m.TTL:   # EXPIRY CONDITION
            return True
    # --------------------------------------------------------------------#

    return False

# Sharded fork choice rule returns a block for every shard
def sharded_fork_choice(shard_ID, starting_blocks, blocks, weighted_blocks, tips_cache=None):
    if tips_cache is None:
        tips_cache = {}

    cache_key = (shard_ID, starting_blocks[shard_ID])
    if cache_key in tips_cache:
        return tips_cache[cache_key]

    # TYPE GUARD
    for ID in starting_blocks.keys():
        assert ID in SHARD_IDS, "expected shard IDs"
        assert isinstance(starting_blocks[ID], Block), "expected starting blocks to be blocks"
        assert starting_blocks[ID] in blocks, "expected starting blocks to appear in blocks"
        assert starting_blocks[ID].is_valid(), "expected valid blocks"

    for b in blocks:
        assert isinstance(b, Block), "expected blocks"
        assert b.is_valid(), "expected valid blocks"

    assert isinstance(starting_blocks, dict), "expected dictionary"
    assert isinstance(weighted_blocks, dict), "expected dictionary"
    for b in weighted_blocks.keys():
        assert b in blocks, "expected weighted blocks to appear in blocks"
        assert isinstance(b, Block), "expected block"
        assert b.is_valid(), "expected valid blocks"
        assert weighted_blocks[b] > 0, "expected positive weights"

    # --------------------------------------------------------------------#

    parent_ID = starting_blocks[shard_ID].parent_ID
    if parent_ID is None:
        ret = fork_choice(starting_blocks[shard_ID], blocks, weighted_blocks)
        tips_cache[cache_key] = ret
        return ret
        

    # THE CHILD SHARD HAS TO FILTER BLOCKS FROM ITS FORK CHOICE
    # AS A FUNCTION OF THE FORK CHOICE OF THE PARENT
    block_filter = []
    for b in blocks:
        # we are only going to filter from children
        if b.shard_ID != shard_ID:
            continue

        if is_block_filtered(shard_ID, b.parent_ID, b, starting_blocks, blocks, weighted_blocks, tips_cache):
            block_filter.append(b)

    # CALCULATE CHILD FORK CHOICE (FILTERED GHOST)
    ret = fork_choice(starting_blocks[shard_ID], blocks, weighted_blocks, block_filter)
    tips_cache[cache_key] = ret
    return ret

