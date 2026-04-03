import 'dart:async';
import 'dart:convert';

import 'package:universal_ble/universal_ble.dart';

import '../../models/provisioning_models.dart';
import '../app_logger.dart';
import 'ble_adapter.dart';

class UniversalBleAdapter implements BleAdapter {
  final _log = AppLogger.get('UniversalBleAdapter');

  StreamSubscription? _scanSubscription;
  StreamSubscription? _valueSubscription;

  @override
  Stream<List<BleDeviceSummary>> scan({
    required String namePrefix,
    String? serviceUuid,
  }) {
    final controller = StreamController<List<BleDeviceSummary>>();
    final found = <String, BleDeviceSummary>{};

    // NOTE: BLE plugin behavior can vary by Windows version and adapter driver.
    // This adapter keeps those assumptions out of UI and state logic.
    UniversalBle.stopScan();
    UniversalBle.startScan();

    _scanSubscription = UniversalBle.scanStream.listen((result) {
      final name = result.name ?? '';
      final matchesName = name.startsWith(namePrefix);
      final matchesService = serviceUuid == null ||
          result.serviceUuids
              .map((e) => e.toLowerCase())
              .contains(serviceUuid.toLowerCase());

      if (!matchesName && !matchesService) {
        return;
      }

      found[result.deviceId] = BleDeviceSummary(
        id: result.deviceId,
        name: name.isEmpty ? 'Unknown Device' : name,
        rssi: result.rssi,
      );
      controller.add(found.values.toList());
    }, onError: (error) {
      _log.warning('Scan error: $error');
      controller.addError(error);
    });

    controller.onCancel = () async {
      await _scanSubscription?.cancel();
      UniversalBle.stopScan();
    };

    return controller.stream;
  }

  @override
  Future<void> connect(String deviceId) async {
    _log.info('Connecting to $deviceId');
    await UniversalBle.connect(deviceId);
    await UniversalBle.discoverServices(deviceId);
  }

  @override
  Future<void> disconnect(String deviceId) async {
    await _scanSubscription?.cancel();
    await _valueSubscription?.cancel();
    await UniversalBle.disconnect(deviceId);
  }

  @override
  Stream<String> subscribeToState(
    String deviceId, {
    required String serviceUuid,
    required String characteristicUuid,
  }) {
    final controller = StreamController<String>();

    UniversalBle.setNotifiable(
      deviceId,
      serviceUuid,
      characteristicUuid,
      BleInputProperty.notification,
    );

    _valueSubscription = UniversalBle.characteristicValueStream.listen((event) {
      if (event.deviceId != deviceId) return;
      if (event.serviceId.toLowerCase() != serviceUuid.toLowerCase()) return;
      if (event.characteristicId.toLowerCase() !=
          characteristicUuid.toLowerCase()) {
        return;
      }
      controller.add(utf8.decode(event.value));
    }, onError: controller.addError);

    controller.onCancel = () async {
      await _valueSubscription?.cancel();
    };

    return controller.stream;
  }

  @override
  Future<void> writeControl(
    String deviceId, {
    required String serviceUuid,
    required String characteristicUuid,
    required List<int> bytes,
  }) async {
    await UniversalBle.writeValue(
      deviceId,
      serviceUuid,
      characteristicUuid,
      bytes,
      BleOutputProperty.withResponse,
    );
  }
}
