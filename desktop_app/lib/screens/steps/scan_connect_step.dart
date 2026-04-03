import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/provisioning_models.dart';
import '../../state/provisioning_controller.dart';
import '../../widgets/wizard_scaffold.dart';

class ScanConnectStep extends StatefulWidget {
  const ScanConnectStep({super.key});

  @override
  State<ScanConnectStep> createState() => _ScanConnectStepState();
}

class _ScanConnectStepState extends State<ScanConnectStep> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ProvisioningController>().startScan();
    });
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();

    return WizardScaffold(
      title: 'Find your InkyCal device',
      subtitle: 'Make sure the display is powered on and within BLE range.',
      error: controller.errorMessage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              FilledButton.icon(
                onPressed: controller.isBusy
                    ? null
                    : () => controller.startScan(),
                icon: const Icon(Icons.refresh),
                label: const Text('Rescan'),
              ),
              const SizedBox(width: 8),
              Text('${controller.scannedDevices.length} device(s) found'),
            ],
          ),
          const SizedBox(height: 16),
          Expanded(
            child: ListView.separated(
              itemCount: controller.scannedDevices.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final BleDeviceSummary d = controller.scannedDevices[index];
                return ListTile(
                  tileColor: Theme.of(context).colorScheme.surfaceContainerLow,
                  title: Text(d.name),
                  subtitle: Text('ID: ${d.id}   RSSI: ${d.rssi ?? '-'}'),
                  trailing: FilledButton(
                    onPressed: controller.isBusy
                        ? null
                        : () => controller.connectToDevice(d),
                    child: const Text('Connect'),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
