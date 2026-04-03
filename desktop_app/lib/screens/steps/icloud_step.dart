import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/provisioning_controller.dart';
import '../../widgets/state_chip.dart';
import '../../widgets/wizard_scaffold.dart';

class ICloudStep extends StatefulWidget {
  const ICloudStep({super.key});

  @override
  State<ICloudStep> createState() => _ICloudStepState();
}

class _ICloudStepState extends State<ICloudStep> {
  final _formKey = GlobalKey<FormState>();
  final _user = TextEditingController();
  final _appPass = TextEditingController();

  @override
  void dispose() {
    _user.dispose();
    _appPass.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();

    return WizardScaffold(
      title: 'iCloud CalDAV setup',
      subtitle: 'Enter your iCloud email and app-specific password.',
      nextStepHint: 'Next: Choose final device settings.',
      error: controller.errorMessage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StateChip(message: controller.lastDeviceState),
          const SizedBox(height: 16),
          SizedBox(
            width: 520,
            child: Form(
              key: _formKey,
              child: Column(
                children: [
                  TextFormField(
                    controller: _user,
                    decoration: const InputDecoration(
                      labelText: 'iCloud Email',
                      border: OutlineInputBorder(),
                    ),
                    validator: (value) {
                      if (value == null || value.trim().isEmpty) {
                        return 'Please enter your iCloud email address.';
                      }
                      if (!value.contains('@')) return 'Please enter a valid email address.';
                      return null;
                    },
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _appPass,
                    decoration: const InputDecoration(
                      labelText: 'App Password (xxxx-xxxx-xxxx-xxxx)',
                      border: OutlineInputBorder(),
                    ),
                    validator: (value) {
                      final text = (value ?? '').trim();
                      if (!RegExp(r'^[a-zA-Z0-9-]{19,24}$').hasMatch(text)) {
                        return 'Please enter a valid iCloud app password.';
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
                        controller.formData.iCloudUser = _user.text.trim();
                        controller.formData.iCloudAppPassword =
                            _appPass.text.trim();
                        await controller.sendICloud();
                      },
                child: const Text('Save iCloud Details'),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                onPressed: controller.isBusy ? null : controller.nextStep,
                child: const Text('Continue to Device Settings'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
