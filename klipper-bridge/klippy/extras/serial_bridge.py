# Expose a spare MCU USART on the host as a pseudo-terminal
#
# Pairs with src/hc32f460/serial_bridge.c. Lets a host service talk to a
# UART display wired to the printer mainboard as if it were a local tty.
#
# [serial_bridge]
# baud: 115200
# pty: ~/printer_data/comms/screen
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, pty, tty, fcntl, logging
import mcu as mcu_module

CHUNK = 48          # must match CHUNK in serial_bridge.c
MCU_BUF = 192       # stay under the 256 byte MCU tx ring (minus slack)
MAX_PENDING = 8192  # host side backlog cap; oldest bytes dropped beyond it

def create_raw_pty(ptyname):
    mfd, sfd = pty.openpty()
    # Raw line discipline: binary data (0xFF terminators) passes untouched
    tty.setraw(sfd)
    fl = fcntl.fcntl(mfd, fcntl.F_GETFL)
    fcntl.fcntl(mfd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    try:
        os.unlink(ptyname)
    except OSError:
        pass
    filename = os.ttyname(sfd)
    os.chmod(filename, 0o660)
    os.symlink(filename, ptyname)
    # Keep sfd open so the master never sees a hangup when clients close
    return mfd, sfd

class SerialBridge:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.name = config.get_name()
        self.mcu = mcu_module.get_printer_mcu(self.printer,
                                              config.get('mcu', 'mcu'))
        self.baud = config.getint('baud', 115200, minval=2400)
        self.byte_time = 10. / self.baud
        self.pty_name = os.path.expanduser(
            config.get('pty', '~/printer_data/comms/screen'))
        self.oid = self.mcu.create_oid()
        self.mcu.add_config_cmd("config_serial_bridge oid=%d baud=%d"
                                % (self.oid, self.baud))
        self.mcu.register_config_callback(self._build_config)
        self.mcu.register_serial_response(
            self._handle_data, "serial_bridge_data oid=%c flags=%c data=%*s",
            self.oid)
        self.send_cmd = None
        self.ready = False
        self.pending = bytearray()
        # Estimated bytes still waiting in the MCU tx ring
        self.mcu_level = 0.
        self.level_time = 0.
        self.overflows = 0
        self.mfd, self.sfd = create_raw_pty(self.pty_name)
        self.fd_handle = self.reactor.register_fd(self.mfd, self._pty_read)
        self.flush_timer = self.reactor.register_timer(self._flush)
        self.printer.register_event_handler("klippy:ready", self._ready)
        self.printer.register_event_handler("klippy:shutdown", self._stop)
        self.printer.register_event_handler("klippy:disconnect",
                                            self._disconnect)
    def _build_config(self):
        cq = self.mcu.alloc_command_queue()
        self.send_cmd = self.mcu.lookup_command(
            "serial_bridge_send oid=%c data=%*s", cq=cq)
    def _ready(self):
        self.ready = True
        self.reactor.update_timer(self.flush_timer, self.reactor.NOW)
    def _stop(self):
        self.ready = False
        del self.pending[:]
    def _disconnect(self):
        # The reactor outlives this object across a host RESTART
        self._stop()
        self.reactor.unregister_fd(self.fd_handle)
        self.reactor.unregister_timer(self.flush_timer)
        for fd in (self.mfd, self.sfd):
            try:
                os.close(fd)
            except OSError:
                pass
        self.mfd = self.sfd = None
    # Display -> host (called from the serial background thread)
    def _handle_data(self, params):
        data = params['data']
        flags = params['flags']
        self.reactor.register_async_callback(
            (lambda e: self._write_pty(data, flags)))
    def _write_pty(self, data, flags):
        if flags:
            # 1=rx overflow, 2=tx overflow, 4=framing error (byte kept)
            self.overflows += 1
            logging.info("%s: line errors (flags=%d, count=%d)",
                         self.name, flags, self.overflows)
        if self.mfd is None:
            return
        try:
            os.write(self.mfd, data)
        except OSError:
            # Nobody is reading the pty and its buffer is full
            pass
    # Host -> display
    def _pty_read(self, eventtime):
        try:
            data = os.read(self.mfd, 4096)
        except OSError:
            return
        if not self.ready:
            return
        self.pending.extend(data)
        if len(self.pending) > MAX_PENDING:
            del self.pending[:len(self.pending) - MAX_PENDING]
        self.reactor.update_timer(self.flush_timer, self.reactor.NOW)
    def _flush(self, eventtime):
        if not self.ready or not self.pending:
            return self.reactor.NEVER
        # Drain the estimate at the UART rate, then top up the MCU ring
        drained = (eventtime - self.level_time) / self.byte_time
        self.mcu_level = max(0., self.mcu_level - drained)
        self.level_time = eventtime
        while self.pending and self.mcu_level + CHUNK <= MCU_BUF:
            chunk = bytes(self.pending[:CHUNK])
            del self.pending[:CHUNK]
            self.send_cmd.send([self.oid, chunk])
            self.mcu_level += len(chunk)
        if not self.pending:
            return self.reactor.NEVER
        # Come back once roughly one chunk has left the MCU
        return eventtime + CHUNK * self.byte_time
    def get_status(self, eventtime):
        return {'overflows': self.overflows, 'pty': self.pty_name}

def load_config(config):
    return SerialBridge(config)
