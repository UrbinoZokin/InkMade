import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app.dart';
import 'services/ble/ble_adapter.dart';
import 'services/ble/universal_ble_adapter.dart';
import 'services/ble/ble_provisioning_service.dart';
import 'state/provisioning_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // NOTE: The BLE plugin is isolated behind [BleAdapter] so that if
  // Windows BLE behavior changes, only the adapter needs updates.
  final BleAdapter adapter = UniversalBleAdapter();
  final bleService = BleProvisioningService(adapter: adapter);

  runApp(
    MultiProvider(
      providers: [
        Provider<BleProvisioningService>.value(value: bleService),
        ChangeNotifierProvider<ProvisioningController>(
          create: (_) => ProvisioningController(bleService: bleService),
        ),
      ],
      child: const InkyCalApp(),
    ),
  );
}
