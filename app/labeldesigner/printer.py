import logging
import os
import stat
import time
from brother_ql.backends.helpers import send
from brother_ql import BrotherQLRaster, create_label
from brother_ql.backends.helpers import get_status
from brother_ql.backends import backend_factory, guess_backend
from flask import Config
from .label import LabelOrientation, LabelType, LabelContent
from brother_ql.models import ALL_MODELS

logger = logging.getLogger(__name__)


class PrinterQueue:
    def __init__(self, model, device_specifier, label_size):
        self.model = model
        self.device_specifier = device_specifier
        self.label_size = label_size
        self._print_queue = []

    def add_label_to_queue(self, label, cut: bool = True, high_res: bool = False):
        self._print_queue.append({
            'label': label,
            'cut': cut,
            'high_res': high_res
        })

    def process_queue(self) -> str:
        if not self._print_queue:
            logger.warning("Print queue is empty.")
            return "Print queue is empty."
        qlr = BrotherQLRaster(self.model)
        for entry in self._print_queue:
            label = entry['label']
            cut = entry['cut']
            high_res = entry['high_res']
            if label.label_type == LabelType.ENDLESS_LABEL:
                rotate = 0 if label.label_orientation == LabelOrientation.STANDARD else 90
            else:
                rotate = 'auto'
            img = label.generate(rotate=False)
            dither = label.label_content != LabelContent.IMAGE_BW
            create_label(
                qlr,
                img,
                self.label_size,
                red='red' in str(self.label_size),
                dither=dither,
                cut=cut,
                dpi_600=high_res,
                rotate=rotate
            )
        self._print_queue.clear()
        try:
            # Simulator: pretend we sent data and return success
            if isinstance(self.device_specifier, str) and self.device_specifier == 'simulation':
                logger.info('Simulated sending %d bytes to simulator printer', len(qlr.data))
                return ""
            if isinstance(self.device_specifier, str) and self.device_specifier == '?':
                return "No printer selected — auto-detect found no compatible printer."

            network_printer = isinstance(self.device_specifier, str) and self.device_specifier.startswith('tcp://')
            logger.info("Sending data to printer at %s", self.device_specifier)
            info = send(qlr.data, self.device_specifier)
            logger.info('Sent %d bytes to printer %s', len(qlr.data), self.device_specifier)
            if network_printer:
                logger.info('Network printer does not provide status information.')
                return ""
            logger.info('Printer response: %s', str(info))
            if info.get('did_print') and info.get('ready_for_next_job'):
                logger.info('Label printed successfully and printer is ready for next job')
                return ""
            logger.warning("Failed to print label")
            return "Failed to print label"
        except Exception as e:
            logger.exception("Exception during sending to printer: %s", e)
            return "Exception during sending to printer: " + str(e)


def get_printer(printer_identifier=None, backend_identifier=None):
    """
    Instantiate a printer object for communication. Only bidirectional transport backends are supported.

    :param str printer_identifier: Identifier for the printer.
    :param str backend_identifier: Can enforce the use of a specific backend.1
    """

    selected_backend = None
    if backend_identifier:
        selected_backend = backend_identifier
    else:
        try:
            selected_backend = guess_backend(printer_identifier)
        except ValueError:
            logger.info("No backend stated. Selecting the default linux_kernel backend.")
            selected_backend = "linux_kernel"

    be = backend_factory(selected_backend)
    BrotherQLBackend = be["backend_class"]
    printer = BrotherQLBackend(printer_identifier)
    return printer


_last_scan_ts = 0
_cached_printers = []
_cached_scan_log = []


def reset_printer_cache():
    global _last_scan_ts, _cached_printers, _cached_scan_log
    _last_scan_ts = 0
    _cached_printers = []
    _cached_scan_log = []


def get_ptr_status(config: Config):
    # Simple in-memory cache for detected printers
    global _last_scan_ts, _cached_printers, _cached_scan_log

    device_specifier = config['PRINTER_PRINTER']
    default_model = config['PRINTER_MODEL']
    simulation_enabled = config.get('PRINTER_SIMULATION', False)

    SIMULATOR_PRINTER = {
        'errors': [],
        'path': 'simulation',
        'media_category': None,
        'media_length': 0,
        'media_type': None,
        'media_width': None,
        'model': default_model,
        'model_code': None,
        'phase_type': 'Simulator',
        'series_code': None,
        'setting': None,
        'status_code': 0,
        'status_type': 'Simulator',
        'tape_color': '',
        'text_color': '',
        'red_support': default_model in [m.identifier for m in ALL_MODELS if m.two_color]
    }

    status = {
        "errors": [],
        "path": device_specifier,
        "media_category": None,
        "media_length": 0,
        "media_type": None,
        "media_width": None,
        "model": "Unknown",
        "model_code": None,
        "phase_type": "Unknown",
        "series_code": None,
        "setting": None,
        "status_code": 0,
        "status_type": "Unknown",
        "tape_color": "",
        "text_color": "",
        "red_support": False
    }
    try:
        # If device_specifier is the default '?', try to auto-detect multiple printers
        if device_specifier == '?':
            now = time.time()
            # Refresh cache every 30 seconds (reset to 0 via reset_printer_cache() after power toggle)
            if now - _last_scan_ts > 30:
                logger.info('Auto-detecting printers: scanning /dev/usb/lp0..lp10')
                found_list = []
                scan_log = []
                for i in range(0, 11):
                    dev = f"/dev/usb/lp{i}"
                    if not os.path.exists(dev):
                        continue
                    if not stat.S_ISCHR(os.stat(dev).st_mode):
                        logger.debug('Skipping %s: not a character device', dev)
                        continue
                    spec = f"file://{dev}"
                    log_entry = {'device': spec, 'found': False, 'model': None, 'error': None}
                    try:
                        printer = get_printer(spec)
                        printer_state = get_status(printer)
                        printer_state.setdefault('path', spec)
                        found_list.append(printer_state)
                        log_entry['found'] = True
                        log_entry['model'] = printer_state.get('model')
                        logger.info('Found compatible printer at %s -> %s', spec, printer_state.get('model'))
                    except Exception as e:
                        log_entry['error'] = str(e)
                        logger.warning('Device %s exists but get_status() failed (%s), adding with unknown status', dev, e)
                        fallback = {
                            'errors': [str(e)],
                            'path': spec,
                            'media_category': None,
                            'media_length': 0,
                            'media_type': None,
                            'media_width': None,
                            'model': default_model,
                            'model_code': None,
                            'phase_type': 'Unknown',
                            'series_code': None,
                            'setting': None,
                            'status_code': 0,
                            'status_type': 'Unknown',
                            'tape_color': '',
                            'text_color': '',
                            'red_support': default_model in [m.identifier for m in ALL_MODELS if m.two_color]
                        }
                        found_list.append(fallback)
                        log_entry['found'] = True
                        log_entry['model'] = default_model
                    scan_log.append(log_entry)
                _cached_printers = found_list
                _cached_scan_log = scan_log
                _last_scan_ts = now

            printers = list(_cached_printers)
            if simulation_enabled:
                printers.append(SIMULATOR_PRINTER.copy())

            if printers:
                first = printers[0]
                for key, value in first.items():
                    status[key] = value
                return {
                    'printers': printers,
                    'selected': status.get('path'),
                    'scan_log': list(_cached_scan_log),
                    **status
                }
            else:
                status['status_type'] = 'Offline'
                status['errors'].append('No compatible printer detected')
                return {
                    'printers': [SIMULATOR_PRINTER.copy()] if simulation_enabled else [],
                    'selected': None,
                    'scan_log': list(_cached_scan_log),
                    **status
                }
        elif device_specifier == 'simulation':
            status.update(SIMULATOR_PRINTER)
            return {
                'printers': [SIMULATOR_PRINTER.copy()],
                'selected': 'simulation',
                'scan_log': [],
                **status
            }
        elif device_specifier.startswith('tcp://'):
            # TCP printers are not supported for status queries
            status['status_type'] = 'Unknown'
            printer = SIMULATOR_PRINTER.copy()
            printer['path'] = device_specifier
            printer['phase_type'] = 'Network Printer'
            printer['status_type'] = 'Network Printer'
            printers = [printer]
            if simulation_enabled:
                printers.append(SIMULATOR_PRINTER.copy())
            status['printers'] = printers
            status['selected'] = device_specifier
            status['scan_log'] = []
            return status
        else:
            printer = get_printer(device_specifier)
            printer_state = get_status(printer)
            for key, value in printer_state.items():
                status[key] = value
            status['red_support'] = status['model'] in [model.identifier for model in ALL_MODELS if model.two_color]
            printers = [dict(status)]
            if simulation_enabled:
                printers.append(SIMULATOR_PRINTER.copy())
            return {
                'printers': printers,
                'selected': status.get('path'),
                'scan_log': [],
                **status
            }
    except Exception as e:
        logger.exception("Printer status error: %s", e)
        status['errors'] = [str(e)]
        status['scan_log'] = list(_cached_scan_log)
        return status
