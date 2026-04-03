import 'dart:async';
import 'dart:convert';

import '../../models/provisioning_models.dart';
import '../app_logger.dart';
import 'ble_adapter.dart';
import 'ble_constants.dart';

class BleProvisioningService {
  BleProvisioningService({required BleAdapter adapter}) : _adapter = adapter {
    AppLogger.init();
  }

  final BleAdapter _adapter;
  final _log = AppLogger.get('BleProvisioningService');

  Stream<List<BleDeviceSummary>> scanForDevices() {
    return _adapter.scan(
      namePrefix: BleConstants.expectedNamePrefix,
      serviceUuid: BleConstants.serviceUuid,
    );
  }

  String? _connectedDeviceId;
  StreamSubscription<String>? _stateSubscription;

  Future<void> connect(String deviceId) async {
    _connectedDeviceId = deviceId;
    await _adapter.connect(deviceId);
    _log.info('Connected to $deviceId');
  }

  Future<void> disconnect() async {
    final id = _connectedDeviceId;
    if (id == null) return;
    await _stateSubscription?.cancel();
    await _adapter.disconnect(id);
    _connectedDeviceId = null;
  }

  Stream<DeviceStateMessage> stateStream() {
    final id = _connectedDeviceId;
    if (id == null) {
      return const Stream<DeviceStateMessage>.empty();
    }

    return _adapter
        .subscribeToState(
          id,
          serviceUuid: BleConstants.serviceUuid,
          characteristicUuid: BleConstants.stateCharacteristicUuid,
        )
        .map((raw) {
      _log.fine('STATE <= $raw');
      return DeviceStateMessage.tryParse(raw);
    }).where((msg) => msg != null).cast<DeviceStateMessage>();
  }

  Future<void> sendCommand(Map<String, dynamic> command) async {
    final id = _connectedDeviceId;
    if (id == null) {
      throw StateError('Not connected to a BLE device');
    }

    final payload = jsonEncode(command);
    _log.info('CONTROL => $payload');
    await _adapter.writeControl(
      id,
      serviceUuid: BleConstants.serviceUuid,
      characteristicUuid: BleConstants.controlCharacteristicUuid,
      bytes: utf8.encode(payload),
    );
  }

  void attachStateListener(void Function(DeviceStateMessage message) onMessage) {
    _stateSubscription?.cancel();
    _stateSubscription = stateStream().listen(onMessage, onError: (error) {
      _log.warning('State stream error: $error');
    });
  }
}
