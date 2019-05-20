import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count
from pathlib import Path

import click
import requests
import appdirs
from eth_abi import encode_single
from eth_utils import function_signature_to_4byte_selector, decode_hex, encode_hex
from web3.auto import w3
from web3.exceptions import NoABIFunctionsFound, MismatchedABI


CHIEF_ADDRESS = '0x9eF05f7F6deB616fd37aC3c959a2dDD25A54E4F5'
CHIEF_BLOCK = 7705361

pool = ThreadPoolExecutor(10)
cache = Path(appdirs.user_cache_dir('chief'))
cache.mkdir(exist_ok=True)


@dataclass
class Voter:
    '''Anyone can vote for multiple proposals (yays).'''
    yays: list = field(default_factory=list)
    weight: Decimal = Decimal()


def get_contract(address):
    '''Get contract interface and cache it.'''
    f = cache / f'{address}.json'
    if not f.exists():
        # cache the response
        abi = get_contract_abi(address)
        f.write_text(json.dumps(abi))
    abi = json.loads(f.read_text())
    return w3.eth.contract(address, abi=abi)


def get_contract_abi(address):
    '''Get contract interface from Etherscan.'''
    resp = requests.get('http://api.etherscan.io/api', params={
        'module': 'contract',
        'action': 'getabi',
        'format': 'raw',
        'address': address,
    })
    try:
        return resp.json()
    except json.JSONDecodeError:
        return


def get_slates(chief):
    '''Get unique sets of proposals.'''
    etches = chief.events.Etch().createFilter(fromBlock=CHIEF_BLOCK).get_all_entries()
    slates = {encode_hex(etch['args']['slate']) for etch in etches}
    return slates


def slates_to_yays(chief, slates):
    '''Concurrently get corresponding votes for slates.'''
    yays = {slate: pool.submit(slate_to_addresses, chief, slate) for slate in slates}
    return {slate: yays[slate].result() for slate in slates}


def slate_to_addresses(chief, slate):
    '''Get all proposals a slate votes for.'''
    addresses = []
    for i in count():
        try:
            addresses.append(chief.functions.slates(slate, i).call())
        except ValueError:
            break
    return addresses


def func_topic(func):
    ''' Convert function signature to ds-note log topic. '''
    return encode_hex(encode_single('bytes32', function_signature_to_4byte_selector(func)))


def get_notes(chief):
    '''Get yays and slate votes.'''
    return w3.eth.getLogs({
        'address': chief.address,
        'topics': [
            [func_topic('vote(address[])'), func_topic('vote(bytes32)')]
        ],
        'fromBlock': CHIEF_BLOCK,
    })


def notes_to_voters(chief, notes, slates_yays):
    '''Recover the most recent votes for each user and their deposit.'''
    voters = defaultdict(Voter)
    for note in notes:
        data = decode_hex(note['data'])[96:]
        try:
            func, args = chief.decode_function_input(data)
        except:
            continue
        sender = w3.toChecksumAddress(note['topics'][1][12:])
        v = voters[sender]
        v.yays = slates_yays.get(encode_hex(args['slate']), []) if 'slate' in args else args['yays']
    deposits = {v: pool.submit(voter_deposit, chief, v) for v in voters}
    for v in voters:
        voters[v].weight = deposits[v].result()
    return voters


def voter_deposit(chief, address):
    '''Get MKR deposit of a user in the governance contract.'''
    return w3.fromWei(chief.functions.deposits(address).call(), 'ether')


def voters_to_results(voters):
    '''Tally the votes.'''
    proposals = Counter()
    for addr in voters:
        for yay in voters[addr].yays:
            proposals[yay] += voters[addr].weight
    return proposals.most_common()


def votes_for_proposal(proposal, voters):
    '''Find all votes for a proposal.'''
    votes = Counter()
    for addr in voters:
        if proposal in voters[addr].yays and voters[addr].weight > 0:
            votes[addr] = voters[addr].weight
    return votes.most_common()


def decode_spell(address):
    '''Decode ds-spell called against mom contract.'''
    spell = get_contract(address)
    whom = spell.functions.whom().call()
    mom = get_contract(whom)
    func, args = mom.decode_function_input(spell.functions.data().call())
    desc = None
    if func.fn_name == 'setFee':
        rate = Decimal(args['ray']) / 10 ** 27
        percent = rate ** (60 * 60 * 24 * 365) * 100 - 100
        desc = f'{percent:.2f}%'
    return {'name': func.fn_name, 'args': args, 'desc': desc}


def get_spells(addresses):
    '''Try to decode all spells.'''
    spells = {}
    for spell in addresses:
        try:
            spells[spell] = decode_spell(spell)
        except (ValueError, NoABIFunctionsFound, MismatchedABI):
            pass
    return spells


def output_text(voters, results, spells, hat):
    '''Output results as text.'''
    for i, (proposal, votes) in enumerate(results, 1):
        click.secho(f'{i}. {proposal} {votes}', fg='green' if proposal == hat else 'yellow', bold=True)
        if proposal in spells:
            s = spells[proposal]
            click.secho(f"spell: {s['name']} {s['desc']} {s['args']}", fg='magenta')
        for voter, weight in votes_for_proposal(proposal, voters):
            click.secho(f'  {voter} {weight}')
        print()


def output_json(voters, results, spells, hat):
    '''Output results as json. Use --json option for that.'''
    data = {'hat': hat, 'proposals': {}}
    for proposal, votes in results:
        data['proposals'][proposal] = {
            'total': votes,
            'voters': dict(votes_for_proposal(proposal, voters)),
            'spell': spells.get(proposal),
        }
    click.secho(json.dumps(data, indent=2, default=str))


@click.command()
@click.option('--json', is_flag=True)
def main(json):
    chief = get_contract(CHIEF_ADDRESS)
    print('got chief')
    slates = get_slates(chief)
    print('got slates')
    slates_yays = slates_to_yays(chief, slates)
    print('got yays')

    notes = get_notes(chief)
    print('got notes')
    voters = notes_to_voters(chief, notes, slates_yays)
    print('got voters')

    results = voters_to_results(voters)
    print('got results')
    spells = get_spells([proposal for proposal, votes in results])
    print('got spells')
    hat = chief.functions.hat().call()
    print('got hat')

    if json:
        output_json(voters, results, spells, hat)
    else:
        output_text(voters, results, spells, hat)


if __name__ == '__main__':
    main()
