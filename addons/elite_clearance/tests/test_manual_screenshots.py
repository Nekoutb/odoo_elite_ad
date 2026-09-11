"""Pictures of the real application, for the user manual.

The owner cannot be asked to screenshot forty screens by hand, and a
manual drawn from memory is a manual that lies the first time a label
changes. CI already drives a real Chrome through this module, so the
same browser takes the pictures: every screen below is the application
as it actually renders, from a database built by the module's own
fixtures.

Opt-in, because it is slow and produces artifacts: set
CLEARANCE_MANUAL_SHOTS to run it. CI sets it on the test job, and the
images come back in the `browser-install` artifact under
screenshots/.

The screens that need a click - a dialog, a tab - are reached by
evaluating the click in the page and waiting for what it opens, which
is the only way: a tour runs in the browser and cannot ask Python for
a screenshot half way through.
"""

import contextlib
import os
import time

from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser

SHOOT = os.environ.get('CLEARANCE_MANUAL_SHOTS')


@tagged('post_install', '-at_install')
class TestManualScreenshots(HttpCase):

    def _click(self, browser, selector, label=""):
        """Click the first element matching a CSS selector, in the page."""
        expression = """
            (() => {
                const el = document.querySelector(%r);
                if (!el) { return "missing"; }
                el.click();
                return "clicked";
            })()
        """ % selector
        result = browser._websocket_request('Runtime.evaluate', params={
            'expression': expression, 'awaitPromise': False})
        outcome = result.get('result', {}).get('result', {}).get('value')
        self.assertEqual(outcome, "clicked",
                         "could not click %s (%s)" % (selector, label))
        time.sleep(1.5)          # let Owl render what the click opened

    def _wait_for(self, browser, selector, timeout=20):
        browser._wait_ready(
            "!!document.querySelector(%r)" % selector, timeout=timeout)

    def test_01_the_screens_the_manual_shows(self):
        if not SHOOT:
            self.skipTest("set CLEARANCE_MANUAL_SHOTS to capture the manual")

        # admin drives the tour: the manual shows what a fully-rightsed
        # user sees, and the per-role differences are described in words
        self.env.ref('base.user_admin').write({'password': 'admin'})

        browser = ChromeBrowser(self, headless=True)
        with self.allow_requests(browser=browser), contextlib.ExitStack() as atexit:
            atexit.enter_context(browser.cleanup)
            self.authenticate('admin', 'admin', browser=browser)
            self.cr.flush()
            self.cr.clear()

            def shot(name, url, wait=".o_content", clicks=()):
                browser.navigate_to("%s%s" % (self.base_url(), url),
                                    wait_stop=True)
                self._wait_for(browser, wait)
                for selector, label in clicks:
                    self._click(browser, selector, label)
                time.sleep(1.0)
                browser.take_screenshot("manual-%s-" % name)

            files = self.env.ref('elite_clearance.action_logistics_file')
            tasks = self.env.ref('elite_clearance.action_clearance_tasks')
            shot("01-files", "/odoo/action-%d" % files.id)
            shot("02-my-tasks", "/odoo/action-%d" % tasks.id)
            shot("03-new-file", "/odoo/action-%d/new" % files.id,
                 wait=".o_form_view")
            # every future waits for its callback; give them a moment
            time.sleep(2.0)
