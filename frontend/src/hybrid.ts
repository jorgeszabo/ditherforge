import { mount } from 'svelte';
import './app.css';
import './hybrid.css';
import Hybrid from './Hybrid.svelte';

mount(Hybrid, { target: document.getElementById('app')! });
