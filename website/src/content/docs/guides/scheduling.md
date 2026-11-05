---
title: Scheduling
description: Run s3mirror from cron or a systemd timer, keep a log of every run, stop runs overlapping, and alert on the right things.
---

s3mirror runs once and exits, so scheduling it is a matter of starting it regularly. It keeps no
state between runs, so a missed or interrupted run is simply caught up by the next one.

## The command

For a scheduled run, write the full log to a file and keep the console for errors:

```bash
s3mirror --config /etc/s3mirror.yaml --log-file /var/log/s3mirror/s3mirror.log
```

With `--log-file` and without `--debug`, the console only gets error lines, and the file gets
everything at debug level with timestamps, including each key copied and deleted. The file is
opened in append mode and each run starts with a `NEW SESSION` header, so one file can hold many
runs. The directory has to exist and be writable: if it isn't, s3mirror stops with a Python
traceback and exit code 1 before connecting to anything.

`--quiet` gives the same errors-only console without a log file. Adding `--quiet` to the command
above changes nothing.

## cron

Cron runs with a minimal `PATH`, so use the full path to the command. `command -v s3mirror` prints
it; for a Homebrew install it's under `$(brew --prefix)/bin`.

```bash title="crontab"
30 2 * * * flock -n /run/lock/s3mirror.lock /usr/local/bin/s3mirror --config /etc/s3mirror.yaml --log-file /var/log/s3mirror/s3mirror.log
```

s3mirror doesn't stop two runs overlapping, and two runs on the same buckets would copy the same
objects twice and compete for the same bandwidth. `flock -n`, from util-linux, skips a
run while the previous one still holds the lock. On systems without `flock`, use whatever locking
the scheduler offers.

Cron mails whatever a job prints. With `--log-file`, that's only error lines, so a mail means
something failed.

## systemd

A oneshot service and a timer. systemd won't start the service again while a run is still going, so
there's no need for a lock:

```ini title="/etc/systemd/system/s3mirror.service"
[Unit]
Description=Mirror S3 buckets with s3mirror
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=s3mirror
ExecStart=/usr/local/bin/s3mirror --config /etc/s3mirror.yaml --log-file /var/log/s3mirror/s3mirror.log
```

```ini title="/etc/systemd/system/s3mirror.timer"
[Unit]
Description=Run s3mirror every night

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now s3mirror.timer
```

Create the `s3mirror` user and give it the log directory, and make `/etc/s3mirror.yaml` readable
only by that user. If you'd rather keep logs in the journal, drop `--log-file`: the normal console
output goes to standard output, which the journal records, though it only reports how many objects
were deleted, not which. With `--debug` instead, the journal gets every key.

A failed run leaves the service in the `failed` state, which `systemctl --failed` and most
monitoring will pick up. Add `OnFailure=` to the `[Unit]` section to run a notification unit as
well.

`systemctl stop` sends `SIGTERM`. s3mirror lets the transfers already running finish, drops the rest
and exits 143, which systemd records as a failure, since the run didn't finish. If a large object
can be in flight, raise `TimeoutStopSec=` (90 seconds by default) in `[Service]`, or systemd kills
it before the transfer completes.

## Rotating the log

s3mirror opens the log file when a run starts and closes it when the run ends, so the file can be
rotated between runs without any signal or `copytruncate`:

```text title="/etc/logrotate.d/s3mirror"
/var/log/s3mirror/s3mirror.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
}
```

## What to alert on

- **A non-zero exit code.** 1 means at least one object failed to copy or delete, a destination
  bucket couldn't be created or listed, an endpoint couldn't be reached, or the config couldn't be
  read. [Exit codes](/s3mirror/reference/exit-codes/) has the full list.
- **`No buckets found to sync`.** The source listed no buckets, or they were all excluded. The run
  exits 0.
- **Runs that take much longer than usual.** s3mirror has no overall time limit, so a very slow
  endpoint holds the run, and with a lock, the runs after it.

A clean run ends its log with `✓ Status: COMPLETED SUCCESSFULLY`, and one with counted errors with
`⚠ Errors encountered: N` and `Status: COMPLETED WITH ERRORS`.
