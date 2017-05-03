import logging
import traceback

from .fetcher import (
    needs_firefox,
    firefox_fetcher,
    requests_fetcher,
    fetch_by_script,
)
from .notifier import create_notifier
from .transformer import transform_factory


logger = logging.getLogger(__name__)


class Checker(object):
    def __init__(self, conf):
        self.conf = conf
        self.downloader = self.downloader_factory()
        self.notifiers = self.create_notifiers()
        self.transform = transform_factory(self.conf)
        self.transform_error = self.transform_error_factory()

    @staticmethod
    def create_from_settings(checks, names=None):
        if names:
            selected_checks = [
                conf
                for conf in checks
                if conf['name'] in names
            ]
            selected_names = [conf['name'] for conf in selected_checks]
            if len(selected_checks) < len(checks):
                logger.info("Filtered list of checks to: %r",
                            ", ".join(sorted(selected_names)))
                checks = selected_checks
            if len(selected_names) < len(names):
                logger.error(
                    "Following check(s) were not found: %r",
                    ", ".join(sorted(set(names).difference(selected_names)))
                )
        return [Checker(conf)
                for conf in checks]

    def check(self):
        ok, content = self.fetch()
        ok, report = self.transform(ok, content)
        if not ok:
            report = self.transform_error(report)
        self.notify(report=report)
        return ok, report

    def fetch(self):
        if self.is_script():
            logger.info("Fetching %r using script",
                        self.conf['name'])
        else:
            logger.info("Fetching %r at %r",
                        self.conf['name'], self.conf['url'])
        try:
            ok, content = self.downloader(self.conf)
        except:
            logger.exception(
                "Exception occured while fetching page"
            )
            ok, content = False, traceback.format_exc()
        return ok, content

    def downloader_factory(self):
        if needs_firefox(self.conf):
            return firefox_fetcher
        elif self.is_script():
            return fetch_by_script
        else:
            return requests_fetcher(self.conf)

    def is_script(self):
        return all((
            'url' not in self.conf,
            'script' in self.conf,
        ))

    def transform_error_factory(self):
        error_policy = self.conf.get('error', 'notify')
        if error_policy == 'ignore':
            return self.mute
        elif error_policy == 'notify':
            return self.echo
        else:
            logger.warning("Unknown error policy: %r", error_policy)
            logger.info("Defaulting to 'notify'")
            return self.echo

    @staticmethod
    def echo(content):
        # content will be logged in notifier
        logger.debug("Notifying on error")
        return content

    @staticmethod
    def mute(content):
        if content:
            logger.error("Ignoring error in %s",
                         repr(content)[:60])
        return None

    def create_notifiers(self):
        notifiers_conf = self.conf.get('notify', [])
        if not notifiers_conf:
            logger.warning(
                "No notifications configured for %r",
                self.conf['name'],
            )
        notifiers = [
            self.notifier_factory(notifier_conf)
            for notifier_conf in notifiers_conf
        ]
        # Drop None:
        return [x for x in notifiers if x]

    def notifier_factory(self, notifier_conf):
        try:
            key, value = next(iter(notifier_conf.items()))
        except AttributeError:
            key, value = notifier_conf, None
        return create_notifier(key, conf=self.conf, value=value)

    def notify(self, report, **_kwargs):
        if report:
            logger.debug('Sending report: %r', report)
            for notifier in self.notifiers:
                try:
                    notifier(report=report)
                except Exception:
                    logger.exception(
                        "Exception occured during sending notification"
                    )
        else:
            logger.debug('Report is empty, skipping notification')
