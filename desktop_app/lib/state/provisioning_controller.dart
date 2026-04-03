import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/provisioning_models.dart';
import '../services/app_logger.dart';
import '../services/ble/ble_provisioning_service.dart';

class ProvisioningController extends ChangeNotifier {
  ProvisioningController({required BleProvisioningService bleService})
      : _bleService = bleService;

  final BleProvisioningService _bleService;
  final _log = AppLogger.get('ProvisioningController');

  WizardStep currentStep = WizardStep.scanConnect;
  final ProvisioningFormData formData = ProvisioningFormData();

  bool isBusy = false;
  String? errorMessage;

  List<BleDeviceSummary> scannedDevices = const [];
  BleDeviceSummary? selectedDevice;
  DeviceStateMessage? lastDeviceState;

  StreamSubscription<List<BleDeviceSummary>>? _scanSubscription;

  bool get isConnected => selectedDevice != null;

  void _setBusy(bool value) {
    isBusy = value;
    notifyListeners();
  }

  Future<void> startScan() async {
    errorMessage = null;
    scannedDevices = const [];
    notifyListeners();

    await _scanSubscription?.cancel();
    _scanSubscription = _bleService.scanForDevices().listen(
      (devices) {
        scannedDevices = devices;
        notifyListeners();
      },
      onError: (error) {
        errorMessage = 'BLE scan failed: $error';
        notifyListeners();
      },
    );
  }

  Future<void> connectToDevice(BleDeviceSummary device) async {
    _setBusy(true);
    errorMessage = null;
    try {
      await _bleService.connect(device.id);
      selectedDevice = device;
      _bleService.attachStateListener((message) {
        lastDeviceState = message;
        notifyListeners();
      });
      currentStep = WizardStep.pairPin;
    } catch (error) {
      errorMessage = 'Connection failed: $error';
    } finally {
      _setBusy(false);
    }
  }

  Future<void> sendPairPin() async {
    await _send({'op': 'pair_pin', 'pin': formData.pin});
  }

  Future<void> sendWifi() async {
    await _send({
      'op': 'wifi_set',
      'ssid': formData.wifiSsid,
      'pass': formData.wifiPassword,
    });
  }

  Future<void> startGoogleDeviceFlow() async {
    await _send({'op': 'oauth_device_start'});
  }

  Future<void> cancelGoogleDeviceFlow() async {
    await _send({'op': 'oauth_device_cancel'});
  }

  Future<void> sendICloud() async {
    await _send({
      'op': 'icloud_set',
      'user': formData.iCloudUser,
      'app_password': formData.iCloudAppPassword,
    });
  }

  Future<void> sendSettings() async {
    await _send(formData.settings.toJsonCommand());
  }

  Future<void> apply() async {
    await _send({'op': 'apply'});
  }

  Future<void> _send(Map<String, dynamic> command) async {
    _setBusy(true);
    errorMessage = null;
    try {
      await _bleService.sendCommand(command);
    } catch (error) {
      _log.warning('sendCommand failed: $error');
      errorMessage = '$error';
    } finally {
      _setBusy(false);
    }
  }

  void nextStep() {
    if (currentStep.index < WizardStep.values.length - 1) {
      currentStep = WizardStep.values[currentStep.index + 1];
      notifyListeners();
    }
  }

  void previousStep() {
    if (currentStep.index > 0) {
      currentStep = WizardStep.values[currentStep.index - 1];
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _scanSubscription?.cancel();
    _bleService.disconnect();
    super.dispose();
  }
}
