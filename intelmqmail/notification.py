from intelmqmail.db import load_events, new_ticket_number, mark_as_sent
from intelmqmail.templates import read_template
from intelmqmail.tableformat import format_as_csv
from intelmqmail.mail import create_mail, clearsign
import pyxarf
import tempfile
import os


class NotificationError(Exception):

    """Base class for notification related exceptions"""


class InvalidDirective(NotificationError):

    """Indicates an invalid notification directive.

    Scripts should raise this exception while processing a directive if
    they have determined that they should handle the directive but
    cannot because of a defect in the directive. Directives can be
    invalid for various reasons, e.g. by referring to unknown CSV
    formats or templates.
    """


class InvalidTemplate(InvalidDirective):

    """Indicates a problem with a template needed for a directive.
    """

    def __init__(self, template_name):
        self.template_name = template_name
        super().__init__("Invalid template %r" % (self.template_name,))


class ScriptContext:

    """Provide the context in which scripts are run.

    The ScriptContext objects provide access to the details of the
    directives the scripts are to create notifications for and to the
    environment in which to do it, such as configuration settings.

    Attributes:
        directive: The aggregated directive for which the script has to
            produce a notification
        config: the mailgen configuration
        logger: the logger the script should use for logging
    """

    def __init__(self, config, cur, gpgme_ctx, directive, logger):
        self.config = config
        self.db_cursor = cur
        self.gpgme_ctx = gpgme_ctx
        self.directive = directive
        self.logger = logger

    def new_ticket_number(self):
        return new_ticket_number(self.db_cursor)

    def load_events(self, columns=None):
        return load_events(self.db_cursor, self.directive["event_ids"], columns)

    def read_template(self):
        template_name = ''
        try:
            template_name = self.directive["template_name"]
            return read_template(self.config["template_dir"], template_name)
        except Exception as e:
            raise InvalidTemplate(template_name) from e

    def maybe_sign(self, body):
        if self.gpgme_ctx:
            body = clearsign(self.gpgme_ctx, body)
        return body

    def mail_format_as_csv(self, format_spec, template=None,
                           substitutions=None, attach_event_data=False):
        """Create an email with the event data formatted as CSV.

        The subject and body of the mail are taken from a template. The
        template can use the following substitutions by default:

            ticket_number: The ticket number assigned by mailgen for the
                notification.
            events_as_csv: The event data formatted as CSV

        If the notification directives specify special aggregation
        criteria, these are also available. Which these are precisely
        depends on the directives, but a common case is to aggregate
        notifications for events that share some information, so if the
        directives specify aggregation by source.asn, this substition is
        also available.

        Args:
            format_spec (TableFormat): a description of the CSV format
                as an instance of :py:class:`TableFormat`.
            template (Template): The template object for the subject and
                body of the mail. If omitted or None, the directive's
                template_name will be used to load the template. See
                :py:meth:`read_template`.
            substitutions (dict): Dictionary mapping strings to strings
                with substitutions. These will be available in templates
                in addition to the ones made available by this method.
            attach_event_data (bool): If true the CSV formatted event
                data will be included in the mail as attachment.

        Return:
            list of EmailNotification instances. The list has one
            element. It's a list so that it can be used directly as a
            return value of a notification script's create_notifications
            function.
        """
        events = self.load_events(format_spec.event_table_columns())

        events_as_csv = format_as_csv(format_spec, events)

        if template is None:
            template = self.read_template()

        ticket = self.new_ticket_number()

        if substitutions is None:
            substitutions = {}
        else:
            substitutions = substitutions.copy()

        substitutions["ticket_number"] = ticket
        substitutions["events_as_csv"] = (events_as_csv if not attach_event_data
                                          else "")

        # Add the information on which the aggregation was based. These are
        # the same in all directives and events that led to this
        # notification, so it can be useful to refer to them in the message
        for key, value in self.directive["aggregate_identifier"]:
            substitutions[key] = value

        subject, body = template.substitute(substitutions)

        attachments = []
        if attach_event_data:
            attachments.append(((events_as_csv,),
                                dict(subtype="csv", filename="events.csv")))

        mail = create_mail(sender=self.config["sender"],
                           recipient=self.directive["recipient_address"],
                           subject=subject, body=body,
                           attachments=attachments, gpgme_ctx=self.gpgme_ctx)
        return [EmailNotification(self.directive, mail, ticket)]

    def mail_format_as_xarf(self, xarf_schema):
        """
        Create Messages in X-Arf Format
        Args:
            xarf_schema: an XarfSchema object, like in 20xarf.py

        Returns:

        """

        # Load the events and their required columns.
        # xarf_schema.event_columns() returns a dict/set/list of column-names
        events = self.load_events(xarf_schema.event_columns())

        sender = self.config["sender"]

        # Read the path to cache X-Arf Schemata from conf
        # if the variable was not set use a tempdir
        schema_cache = self.config.get("xarf_schemacache",
                                       tempfile.gettempdir() + os.sep)

        # This automatism is setting the Domain-Part within the
        # report_id of the X-ARF Report. If the parameter
        # xarf_reportdomain was not set in the the config, the senders
        # domain name is used.
        reportid_domain = self.config.get("xarf_reportdomain",
                                          sender.split("@")[1])

        template = self.read_template()

        returnlist_notifications = []

        # Create an X-Arf Message for every event
        for event in events:
            # Get a new ticketnumber for each event
            ticket = self.new_ticket_number()
            report_id = "{}@{}".format(ticket, reportid_domain)

            subject, body = template.substitute({"ticket_number": ticket})

            params = {
                'schema_cache': schema_cache,
                'reported_from': sender,
                'report_id': report_id,
                # 'useragent': "IntelMQ-Mailgen,  # Useragent is set by pyxarf __useragent__
                }
            # now, as we know the events data and the intelmq-fields and
            # the mapping of these fields to the X-ARF Schema, pass the
            # event into the XarfSchema's xarf_params function in order
            # to resolve mapping of the events data to the X-Arf-Key
            params.update(xarf_schema.xarf_params(event))

            # Create an X-ARF Message using the pyxarf library.
            # The lib downloads the schema from schema_url automagically
            # and stores it in the schema_cache
            xarf_object = pyxarf.Xarf(**params)

            mail = self.create_xarf_mail(subject, body, xarf_object)

            returnlist_notifications.append(EmailNotification(self.directive,
                                                              mail, ticket))

        return returnlist_notifications

    def create_xarf_mail(self, subject, body, xarf_object):
        """

        Args:
            xarf_object:

        Returns:

        """
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formatdate

        msg = MIMEMultipart()
        msg.attach(MIMEText(body))
        msg.attach(MIMEText(xarf_object.to_yaml('machine_readable'), 'plain',
                            'utf-8'))

        msg.add_header("From", self.config["sender"])
        msg.add_header("To", self.directive["recipient_address"])
        msg.add_header("Subject", subject)
        msg.add_header("Auto-Submitted", "auto-generated")
        msg.add_header("X-ARF", "PLAIN")  # TODO BULK IS NOT SUPPORTED YET
        msg.add_header("Date", formatdate(timeval=None, localtime=True))

        return msg


class SendContext:

    def __init__(self, cur, smtp):
        self.cur = cur
        self.smtp = smtp

    def mark_as_sent(self, directive_ids, ticket):
        mark_as_sent(self.cur, directive_ids, ticket)


class Notification:

    def __init__(self, directive):
        self.directive = directive

    def send(self, context):
        pass


class EmailNotification(Notification):

    def __init__(self, directive, email, ticket):
        self.email = email
        self.ticket = ticket
        super().__init__(directive)

    def send(self, send_context):
        send_context.smtp.send_message(self.email)
        send_context.mark_as_sent(self.directive["directive_ids"], self.ticket)