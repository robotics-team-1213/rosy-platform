# Remote Chromium log and image fingerprints

Raw logs: `C:/DevTemp/recording-handoff-ui-followup-browser-final/`. These are initial results; run-4 failed, and the corrected whole two-file group later passed 19 in `C:/DevTemp/recording-handoff-ui-rail-green/run-1.txt`.

| Log | First result | SHA-256 |
|---|---|---|
| run-1.txt | 148 passed in 476.01s (0:07:56) | 5593cddbb7dc9bb4619d6e1b30c108dcc96c57c6b40c958a8062f163b47d4f8f |
| run-2.txt | 40 passed in 155.23s (0:02:35) | b5326de5d03a56e5b38c0a15d570f39ba35a3542d80262864eebb539afb89fca |
| run-3.txt | 7 passed in 24.42s | 13e570067e7691d86ca6947a474817ed3c8d5cabbdd26e2da869483d7a92eea4 |
| run-4.txt | 1 failed, 18 passed in 64.77s (0:01:04) | 7909a39ac4bbd75861a210dfb49c1dce81d5a18c9e8127708de330a35243b049 |
| run-5.txt | 14 passed in 37.23s | 2e50302780755fb4c97905459fbceef8b540e56587998d397aa4aea56e6bcec7 |
| run-6.txt | 5 passed in 15.92s | 3edd1bab692a334a2c97660ec8de06d7c8caeefdf094e88b365a3f7394a8cc79 |
| run-7.txt | 10 passed in 47.48s | 33bd853285e8509d169e5a08f1285cb9ddfde518f0d5455509b016c819f6f336 |
| run-8.txt | 20 passed in 45.75s | 8e5d7b933ec912034ce50576d5df6a3b78aeaaad13fc706201c9ebcaf3bcbf3a |

Screenshots: `C:/DevTemp/recording-handoff-ui-followup-screenshots/`. Saved-final captures bind to 54fa5d9e7c, navigation to 147e97ab70, alert-final to 030c2fb110. Navigation's original read-error full-viewport capture does not show the alert; alert-final supplies an element crop after viewport assertions.

| Capture | SHA-256 |
|---|---|
| saved-final/recording-learning-review-saved-1440-dark.png | aaf961d62038b30ca5b41337c5c423334c73e7b52d62dd90ab89bd8ff5d378db |
| saved-final/recording-learning-review-saved-320-light.png | 4bda4bc114397d543aa7aea3c62923bbb1b96ddc45b894101992f38e2e8a185b |
| navigation/omx-all-tools-1440.png | b6fe6681007dc02cea094a0e8385c254f558790787bef0775fb7ed1b78bf6e2e |
| navigation/omx-all-tools-320.png | 1ab260bf0081f5e9359007aee22fa185dbe24dc83cddcc1db003f41c1e882720 |
| navigation/omx-archive-1440-dark.png | 78a4e477cb2c0374c9954556b64e606400f6dc403d4d92129f421183ace06fed |
| navigation/omx-archive-320-light.png | 2e63f3e4762698e1aa8dfc881fe7cd607b910fabe857c0d60d9497fecf30fc27 |
| navigation/omx-center-read-failure.png | c5c3a0038ad98853325d4a107823b2785fc15d34bbf0a829edd24a1084ba6fbf |
| navigation/omx-nested-review-1440.png | 4767edba18de4972515cc1c3c8587711152acfcc952e8645996c7a6d7d11f023 |
| navigation/omx-nested-review-320.png | 109c5723410b9137b2f63a1f39001244be71197ec37e4356a568486edb8325c6 |
| alert-final/omx-center-read-failure.png | e45254c6b34be14715488820871f154f33f9d5890ebc53fb762d4b10906a92e1 |

