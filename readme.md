# maker-chief
tally makerdao governance votes

## about

this tool fetches all `etch` and `vote` events from makerdao governance contract (see [ds-chief](https://github.com/dapphub/ds-chief)), tallies the votes and breaks them down by proposal and voters.

it also tries to recover what proposals are doing assuming they are [ds-spell](https://github.com/dapphub/ds-spell) executed on [mom](https://github.com/makerdao/sai/blob/master/src/mom.sol) contract. functions like `setFee` can be additionally parsed to show more meaningful values.

the text output format is:

```
<n>. <proposal> <votes>
spell: <func> <desc> <args>
  <voter> <votes>
```

the currently active proposal (`hat`) is shown in green.

the json format is self-explanatory. note that the numbers are encoded as text to avoid rounding errors.

## installation

install python 3.7 and a local ethereum node.

```bash
pip3 install maker-chief 
```

## usage

run `maker-chief` or `maker-chief --json`
