# check_reprise_server

A Nagios/Icinga plugin that checks a Reprise License Manager (RLM) server
with Reprise's `rlmutil`. Python 3.7 or newer, standard library only.

It checks that the `rlm` server and its ISV server(s) are up, reports the
usage of every product as performance data, and alerts on the product that
expires first.

Sibling project of [check_flexlm_server](https://github.com/ThomasWagnerJKU/check_flexlm_server)
for FlexLM; RLM is a different, unrelated license manager (used e.g. by
Sonnet Software) with its own protocol and `rlmutil` tool, so the two
plugins don't share any code, but the interface and output are kept as
close as reasonably possible for consistency.

## Usage

```sh
check_reprise_server -l /opt/sonnet/rlmutil -H licsrv.example.com -p 5852
check_reprise_server -l /opt/sonnet/rlmutil -H licsrv.example.com -p 5852 -w 60: -c 14:
check_reprise_server -l /opt/sonnet/rlmutil -H localhost -p 5852 -s monitor@licsrv.example.com
```

```
RLM OK - 3 feature(s), 3 of 2005 licenses in use, embeowulf expires on 2099-10-01, in 30 days | days_left=30;30;7 'xgeom'=3;;;0;1000 'embeowulf'=0;;;0;5 'soncustomer'=0;;;0;1000
```

| Option | Meaning |
|---|---|
| `-l`, `--rlmutil` | Path of `rlmutil` (required); with `-s`, the path on that host |
| `-H`, `--hostname` | License server (required) |
| `-p`, `--port` | Port of `rlm` (default: 5053) |
| `-w`, `--warning` | Warning range for the days until the earliest expiry (default: `30:`) |
| `-c`, `--critical` | Critical range for the days until the earliest expiry (default: `7:`) |
| `-t`, `--timeout` | Timeout in seconds for the rlmutil call (default: 30) |
| `-s`, `--ssh` | Run rlmutil on this `[USER@]HOST` via ssh, see below |
| `-V`, `--version` | Show the version |

The plugin runs `rlmutil rlmstat -a -c PORT@HOST` for the state of the rlm
server, the ISV server(s) and the usage and expiry of every product. Unlike
FlexLM's `lmstat -a`/`lmstat -i` split, a single RLM call already reports
both usage and expiry, so only one `rlmutil` call is made.

### Thresholds

`-w` and `-c` take the
[monitoring plugins range format](https://www.monitoring-plugins.org/doc/guidelines.html#THRESHOLDFORMAT)
and apply to the number of days until the earliest expiry date of any
product. As fewer days are worse, use lower bounds: `30:` alerts below 30
days. An expired product has a negative number of days left. Products that
never expire (`exp: permanent`) are not considered; if none expires, the
expiry check is OK.

### Performance data

- `days_left`: days until the earliest expiry, with the thresholds
- one entry per counted product: licenses in use, with 0 and the licensed
  count as minimum and maximum. A product name that two ISV servers share
  is prefixed with the ISV, e.g. `'otherisv/shared'`.

### States

- **CRITICAL**: the rlm server is down or does not answer within `-t`, an
  ISV server is down, or the earliest expiry is outside `-c`
- **WARNING**: the earliest expiry is outside `-w`
- **UNKNOWN**: rlmutil cannot be run, the server reports no products, or the
  command line is wrong

The plugin prints exactly one line.

## Without rlmutil on the monitoring host

RLM's protocol between rlmutil and rlm is proprietary, so the plugin needs
`rlmutil`. It does not have to be on the monitoring host, though:

- **`-s`/`--ssh`**: the plugin runs rlmutil on another host, typically the
  license server itself, where rlmutil is installed alongside rlm. `-l` is
  then the path of rlmutil on that host and `-H` is resolved there, so
  `-H localhost` checks the server the ssh connection goes to. The
  monitoring user needs key based access; restrict the key on the license
  server with `command=`/`restrict` in `authorized_keys` if you like.
- **An agent on the license server**: run check_reprise_server there via
  NRPE, the Icinga 2 agent or check_by_ssh, with a local `-l`.
- **Liveness only**: `check_tcp` against the rlm port and the ISV server
  port tells whether the daemons listen, but not their usage or expiry.

## Tests

```sh
python3 -m unittest -v
```

The tests replay recorded rlmstat output through a fake rlmutil and a fake
ssh.

## License

GPL-2.0-or-later, see [LICENSE](LICENSE).
