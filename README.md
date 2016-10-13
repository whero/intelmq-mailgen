IntelMQ Mailgen
===============

IntelMQ command line tool to process events.

Call `intelmqcbmail --help` to see the current usage. 

Installation
============

Dependencies
------------

As a Python3 application, see the `install_requires` section
in setup.py for its dependencies.

If you use setuptools, it will check the hard requirements
and install a runable script. For an installation from source:
```
pip3 install -v e .
```

**In order to use IntelMQ Mailgen, you require a working certbund-contact-expert
in IntelMQ, as Mailgen makes use of information and data which is not available
in the IntelMQs default fields.**

IntelMQ Configuration
---------------------

For Mailgen to work, the following IntelMQ bots will need to be configured
first:

 1. expert/certbund-contact
 2. output/postgresql

You **must follow the setup instructions for these bots** before
setting up Mailgen.

Preparing Input Data for Mailgen
--------------------------------

IntelMQ Mailgen makes certain assumptions about the input data it receives.
Currently, it expects `classification.identifier` to be present.  It may
therefore be necessary to first prepare the data fed to Mailgen.

IntelMQ comes with a "modify" expert bot that can be added to the queue to
enrich feed data.

Database
--------

The `intelmq-events` database and the `intelmq` database-user
should already have set up by the configuration of the output/postgresql bot.  
For use with Mailgen it needs to be extended:

As database-superuser (usually via system user postgres):

1. Create a new database-user:
    createuser --encrypted --pwprompt intelmq_mailgen

2. Extend the database:
    psql -f sql/notifications.sql intelmq-events

3. Grant `intelmq` the right to insert new events via a trigger:
    psql -c "GRANT eventdb_insert TO intelmq" intelmq-events

4. Grant the new user the right to send out notifications:
    psql -c "GRANT eventdb_send_notifications TO intelmq_mailgen" intelmq-events


Interaction with IntelMQ and the events database
------------------------------------------------

Once you applied `sql/notifications.sql` a trigger called
`events_insert_notification_trigger` was added to you events-table.
This trigger calls an sql-procedure `events_insert_notifications_for_row`,
which extracts data from an event which is relevant to create a notification,
everytime an event is inserted into the events table.

This data contains:
 - E-Mail address
 - Classification Type of the event
 - Feedname of the event
 - Data-Format the contact prefers
 - ID of the event
 - Source IP-address of the event


Ticket Numbers
--------------

For every email sent by Mailgen a ticket number is generated. If a mail
was successfully sent, this number is stored in the notifications table,
together with a timestamp when the mail was sent.


Configuration
=============

`intelmq-mailgen` currently searches for configuration files in two places:

 1. `$HOME/.intelmq/intelmq-mailgen.conf` and
 2. `/etc/intelmq/intelmq-mailgen.conf`.

Settings are read from both files with the one in the user's home directory
taking precedence.

Both files must be in JSON format.  A complete example can be found in
`intelmq-mailgen.conf.example`.

OpenPGP Signatures
------------------

`gnupg_home` has to point to the GnuPG home directory for email signatures.
It must:

 * contains the private and public key parts for the OpenPGP signature without
   password protection.
 * is read/writable for the user running intelmq-mailgen.

For example, the following steps will create such a directory
and import a test signing key.

```
GNUPGHOME=/tmp/gnupghome mkdir $GNUPGHOME
chmod og-rwx $GNUPGHOME
GNUPGHOME=/tmp/gnupghome gpg2 --list-secret-keys
GNUPGHOME=/tmp/gnupghome gpg2 --import src/intelmq-mailgen/tests/keys/test1.sec
```

Depending on your GnuPG version you may want to set additional options
by editing `$GNUPGHOME/gpg.conf`.

For example, the following settings will set the default digest algorithm,
suppress emitting the GnuPG version, and add a comment line for signatures:

```
personal-digest-preferences SHA256
no-emit-version
comment Key verification <https://example.org/hints-about-verification>
```
(See the GnuPG documentation for details.)

Now, you should be able to sign using this key withtout being prompted for
a passphrase.  Try, for example:

```
echo Moin moin. | GNUPGHOME=/tmp/gnupghome gpg2 --clearsign --local-user "5F503EFAC8C89323D54C252591B8CD7E15925678"
```

Templates
---------

`template_dir` must contain the email templates you want to use with IntelMQ
Mailgen.  You may organize templates in subdirectories.

The first line of a template file is used as the subject line
for mail sent by `intelmq-mailgen`. The remaining lines will become
the mail body. The body may optionally be separated from the subject line
by one or more empty lines.

Both subject and body text will be interpreted as
[Python3 Template strings](https://docs.python.org/3/library/string.html#template-strings)
and may allow some substitutions depending on the format.

The subject line allows for
 * `${ticket_number}`
 * `${asn}` for emails grouped by as-number.

For instance, CSV-based formats replace the above two
values and `${events_as_csv}` in the body
with the CSV-formatted event data.


Feed-specific Templates
-----------------------

For the format `feed_specific` IntelMQ Mailgen ignores the template that may
have been set by the Contact DB bot and chooses a template based on the feed's
`feed.name`. Please note that this only works for feeds explicitely supported by
Mailgen.

Feed-specific template file names follow the pattern `template-FEEDNAME.txt`
where `FEEDNAME` is replaced by the events' `feed.name` attributes.

Mailgen is capable of aggregating data from different feeds into one email.
Currently this is done for Shadowservers "Sinkhole-HTTP-Drone",
"Botnet-Drone-Hadoop" and ""Microsoft-Sinkhole" feeds. Use a template named
"template-generic_malware.txt" in oder to address these feeds.
Some example templates are distributed with Mailgen.


Errors
======

Mailgen tries to be as robust as possible, in order to keep sending emails
whenever possible.
If it can't find templates, for instance, it will continue with the next e-mail
and log an error message and the stacktrace.

The error message contains information about the emails
that could not be sent. The `idmap` within the json part is a json dict
of database ids for events in the `events` table.
Each with a list of database ids for the corresponding rows of
the `notifications` table.


Developer Information
=====================

Security Considerations
-----------------------
 * It is assumed that we need to protect against malicious external 
data coming 
to us via the database. 
 * We do not need (or can) protect against local attacks with administration rights.
 * As our command will be able to run with and witout user interaction, 
we assume that only users with administration rights 
have access to the machine and are allowed to start the interactive variant.
 * The private key material for signing will have
no extra protection by passphrase, thus the system itself 
needs to be secured adequately. (This can include separating
to setup intelmq itself on a different machine with only access 
to fill the database.)
* We should pay attention preventing that the complete system 
becomes an effective signature (or encryption) oracle. 
To explain: Consider an attacker who will receive an automatic notification 
from our system. If this attacker also can trigger a warning over 
an used feed, she may partly control which plaintext is to be signed 
(or somewhere encrypted) and get the automated result. There is a small
potential that this may be used for an adaptive-plaintext attack 
under some circumstances.


Column Names
------------

It is possible to define names for the CSV-columns in code. This can be
achieved by altering the `feed_specific_formats` dictionary.
We already configured some feeds.
Each pair consists of the IntelMQ-internal identifier and the column title.


Transformations
---------------

Currently, data is not transformed when it is being added to the CSV output.

Mailgen always removes the "UTC" notations from time stamps in `time.source`.
It ensures that time stamps will always be UTC.

Testing
-------

An easy way to test the actual sending of emails is to use Python's
`smtpd` module running the `DebuggingServer`:

    python3 -m smtpd -d -n -c DebuggingServer localhost:8025 

(Don't forget to configure the corresponding
SMTP host and port in your config.)

If you want to capture emails in Maildir format you can use
https://pypi.python.org/pypi/dsmtpd/0.2.2:
```sh
git clone https://github.com/bernhardreiter/dsmtpd.git
cd dsmtpd
# now you need to have python3-docopt installed
# or drop docopt.py in from https://github.com/docopt/docopt
python3 -c 'from dsmtpd._dsmtpd import *; main()' -i localhost -p 8025 -d /path/to/Maildir
```

`/path/to/Maildir` has to be either an existing
[Maildir](https://en.wikipedia.org/wiki/Maildir) or non-existing,
in which case it will be created by dsmtpd.

You can access the Maildir with mutt, for example:
```
mutt -f  /path/to/Maildir
```
Hint: By default `Esc P` will trigger mutt's `<check-traditional-pgp>`
[function](http://www.mutt.org/doc/manual/#reading-misc), in case you
want to check a no-MIME signature.


Test Suite
----------

The test suite is split into two parts because some tests may fail depending on
hardware specs (execution time) and their failure would not indicate errors per
se.

The regular unit tests which must succeed can be started with ``make check``;
to run the complete test suite, use ``make check_all``.


History
=======

The intelmq-mailgen file was initially copied from
https://github.com/certat/intelmq/blob/a29da5d798bd114535326ffdd2f5000c4b6a21e7/intelmq/bin/intelmqcli (revision from 2016-03-08).
