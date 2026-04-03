import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/provisioning_controller.dart';
import '../../widgets/state_chip.dart';
import '../../widgets/wizard_scaffold.dart';

class WifiStep extends StatefulWidget {
  const WifiStep({super.key});

  @override
  State<WifiStep> createState() => _WifiStepState();
}

class _WifiStepState extends State<WifiStep> {
  final _formKey = GlobalKey<FormState>();
  final _ssid = TextEditingController();
  final _pass = TextEditingController();

  @override
  void dispose() {
    _ssid.dispose();
    _pass.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();

    return WizardScaffold(
      title: 'Configure Wi‑Fi',
      subtitle: 'Enter the Wi‑Fi network your device should use.',
      nextStepHint: 'Next: Link your calendar accounts.',
      error: controller.errorMessage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StateChip(message: controller.lastDeviceState),
          const SizedBox(height: 16),
          SizedBox(
            width: 480,
            child: Form(
              key: _formKey,
              child: Column(
                children: [
                  TextFormField(
                    controller: _ssid,
                    decoration: const InputDecoration(
                      labelText: 'Wi‑Fi SSID',
                      border: OutlineInputBorder(),
                    ),
                    validator: (value) => (value == null || value.trim().isEmpty)
                        ? 'Please enter your Wi‑Fi network name.'
                        : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _pass,
                    decoration: const InputDecoration(
                      labelText: 'Wi‑Fi Password',
                      border: OutlineInputBorder(),
                    ),
                    obscureText: true,
                    validator: (value) {
                      if ((value ?? '').length < 8) {
                        return 'Password must be at least 8 characters long.';
                      }
                      return null;
                    },
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              FilledButton(
                onPressed: controller.isBusy
                    ? null
                    : () async {
                        if (!_formKey.currentState!.validate()) return;
                        controller.formData.wifiSsid = _ssid.text.trim();
                        controller.formData.wifiPassword = _pass.text;
                        await controller.sendWifi();
                      },
                child: const Text('Save Wi‑Fi on Device'),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                onPressed: controller.isBusy ? null : controller.nextStep,
                child: const Text('Continue to Google Setup'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
