Pod::Spec.new do |s|
  s.name           = 'ApolloSlm'
  s.version        = '1.0.0'
  s.summary        = "ApolloSG on-device small language model (Apple Foundation Models)."
  s.description    = "Runs Apple's on-device foundation model for advisory pre-screening and plain-language explanations."
  s.author         = ''
  s.homepage       = 'https://apollo.local'
  s.license        = { :type => 'Proprietary' }
  s.platforms      = { :ios => '16.4' }
  s.source         = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  # FoundationModels is weak-linked: it exists only on iOS 26+, and older systems report "unavailable".
  s.weak_frameworks = 'FoundationModels'
  s.source_files = "**/*.{h,m,swift}"
end
