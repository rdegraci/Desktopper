import contextlib
import io
import unittest
from unittest import mock

from app import server


class PortArgTests(unittest.TestCase):
    def test_omitted_port_is_none(self) -> None:
        self.assertIsNone(server._parse_args([]).port)

    def test_valid_port(self) -> None:
        self.assertEqual(server._parse_args(["--port", "8123"]).port, 8123)

    def test_invalid_ports_exit_with_error(self) -> None:
        for bad in ("abc", "0", "65536", "-1", "80.5"):
            err = io.StringIO()
            with self.subTest(bad=bad), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    server._parse_args(["--port", bad])
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("invalid port", err.getvalue())

    def test_help_documents_port(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            server._parse_args(["--help"])
        self.assertIn("--port", out.getvalue())

    def test_invalid_port_does_not_start_server(self) -> None:
        with mock.patch.object(server, "load_config") as load, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                server.main(["--port", "99999"])
        load.assert_not_called()

    def test_main_uses_cli_port(self) -> None:
        cfg = mock.Mock(bind="127.0.0.1", port=8000)
        fake_app = mock.Mock()
        create_app = mock.Mock(return_value=fake_app)
        with mock.patch.multiple(
            server,
            load_config=mock.Mock(return_value=cfg),
            setup_logging=mock.DEFAULT,
            ensure_host_tables=mock.DEFAULT,
            ensure_owner=mock.DEFAULT,
            run_startup_hooks=mock.DEFAULT,
            start_scheduler=mock.DEFAULT,
            log_server_start=mock.DEFAULT,
            create_app=create_app,
        ), mock.patch.object(server.BOOTSTRAP_CSS.__class__, "is_file", return_value=True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                server.main(["--port", "9001"])
        self.assertIn("http://127.0.0.1:9001/", out.getvalue())
        fake_app.run.assert_called_once_with(
            host="127.0.0.1", port=9001, debug=False, use_reloader=False
        )
        create_app.assert_called_once_with(port=9001)

    def test_main_without_port_keeps_config_port(self) -> None:
        cfg = mock.Mock(bind="127.0.0.1", port=8000)
        fake_app = mock.Mock()
        with mock.patch.multiple(
            server,
            load_config=mock.Mock(return_value=cfg),
            setup_logging=mock.DEFAULT,
            ensure_host_tables=mock.DEFAULT,
            ensure_owner=mock.DEFAULT,
            run_startup_hooks=mock.DEFAULT,
            start_scheduler=mock.DEFAULT,
            log_server_start=mock.DEFAULT,
            create_app=mock.Mock(return_value=fake_app),
        ), mock.patch.object(server.BOOTSTRAP_CSS.__class__, "is_file", return_value=True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                server.main([])
        self.assertIn("http://127.0.0.1:8000/", out.getvalue())
        fake_app.run.assert_called_once_with(
            host="127.0.0.1", port=8000, debug=False, use_reloader=False
        )


if __name__ == "__main__":
    unittest.main()
