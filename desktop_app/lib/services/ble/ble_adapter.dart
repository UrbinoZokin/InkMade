import '../../models/provisioning_models.dart';

abstract class BleAdapter {
  Stream<List<BleDeviceSummary>> scan({
    required String namePrefix,
    String? serviceUuid,
  });

  Future<void> connect(String deviceId);
  Future<void> disconnect(String deviceId);

  Stream<String> subscribeToState(
    String deviceId, {
    required String serviceUuid,
    required String characteristicUuid,
  });

  Future<void> writeControl(
    String deviceId, {
    required String serviceUuid,
    required String characteristicUuid,
    required List<int> bytes,
  });
}
